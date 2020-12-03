from typing import List, TYPE_CHECKING

from aat.core import Instrument, ExchangeType, Event, Order, Trade
from aat.config import Side
from aat.exchange import Exchange

from .execution import OrderManager
from .portfolio import PortfolioManager
from .risk import RiskManager

if TYPE_CHECKING:
    from aat.engine import TradingEngine


class StrategyManagerOrderEntryMixin(object):
    _engine: "TradingEngine"
    _exchanges: List[Exchange]
    _strategy_trades: dict
    _strategy_open_orders: dict
    _strategy_past_orders: dict
    _alerted_events: dict
    _risk_mgr: RiskManager
    _order_mgr: OrderManager
    _portfolio_mgr: PortfolioManager

    #####################
    # Order Entry Hooks #
    #####################
    # TODO ugly private method

    async def _onBought(self, strategy, trade: Trade):
        # append to list of trades
        self._strategy_trades[strategy].append(trade)

        # push event to loop
        ev = Event(type=Event.Types.BOUGHT, target=trade)
        self._engine.pushTargetedEvent(strategy, ev)

        # synchronize state when engine processes this
        self._alerted_events[ev] = (strategy, trade.my_order)

    # TODO ugly private method
    async def _onSold(self, strategy, trade: Trade):
        # append to list of trades
        self._strategy_trades[strategy].append(trade)

        # push event to loop
        ev = Event(type=Event.Types.SOLD, target=trade)
        self._engine.pushTargetedEvent(strategy, ev)

        # synchronize state when engine processes this
        self._alerted_events[ev] = (strategy, trade.my_order)

    # TODO ugly private method

    async def _onReceived(self, strategy, order: Order):
        # push event to loop
        ev = Event(type=Event.Types.RECEIVED, target=order)
        self._engine.pushTargetedEvent(strategy, ev)

        # synchronize state when engine processes this
        self._alerted_events[ev] = (strategy, order)

    async def _onCanceled(self, strategy, order: Order):
        # push event to loop
        ev = Event(type=Event.Types.CANCELED, target=order)
        self._engine.pushTargetedEvent(strategy, ev)

        # synchronize state when engine processes this
        self._alerted_events[ev] = (strategy, order)

    # *********************
    # Order Entry Methods *
    # *********************

    async def newOrder(self, strategy, order: Order):
        """helper method, defers to buy/sell"""
        # ensure has list
        if strategy not in self._strategy_open_orders:
            self._strategy_open_orders[strategy] = []

        if strategy not in self._strategy_past_orders:
            self._strategy_past_orders[strategy] = []

        if strategy not in self._strategy_trades:
            self._strategy_trades[strategy] = []

        # append to open orders list
        self._strategy_open_orders[strategy].append(order)

        # append to past orders list
        self._strategy_past_orders[strategy].append(order)

        # TODO check risk
        order, approved = await self._risk_mgr.newOrder(strategy, order)

        # was this trade allowed?
        if approved:
            # send to be executed
            received = await self._order_mgr.newOrder(strategy, order)

            if received:
                self._engine.pushTargetedEvent(
                    strategy, Event(type=Event.Types.RECEIVED, target=order)
                )
                return order

        # raise onRejected
        self._engine.pushTargetedEvent(
            strategy, Event(type=Event.Types.REJECTED, target=order)
        )
        return order

    async def cancelOrder(self, strategy, order: Order):
        """cancel an open order"""
        ret = await self._order_mgr.cancelOrder(strategy, order)
        if ret:
            await self._onCanceled(strategy, order)
            return order

        # TODO something else?
        self._engine.pushTargetedEvent(
            strategy, Event(type=Event.Types.REJECTED, target=order)
        )
        return order

    def orders(
        self,
        strategy,
        instrument: Instrument = None,
        exchange: ExchangeType = None,
        side: Side = None,
    ):
        """select all open orders

        Args:
            instrument (Instrument): filter open orders by instrument
            exchange (ExchangeType): filter open orders by exchange
            side (Side): filter open orders by side
        Returns:
            list (Order): list of open orders
        """
        # ensure has list
        if strategy not in self._strategy_open_orders:
            self._strategy_open_orders[strategy] = []

        ret = self._strategy_open_orders[strategy].copy()
        if instrument:
            ret = [r for r in ret if r.instrument == instrument]
        if exchange:
            ret = [r for r in ret if r.exchange == exchange]
        if side:
            ret = [r for r in ret if r.side == side]
        return ret

    def pastOrders(
        self,
        strategy,
        instrument: Instrument = None,
        exchange: ExchangeType = None,
        side: Side = None,
    ):
        """select all past orders

        Args:
            instrument (Instrument): filter open orders by instrument
            exchange (ExchangeType): filter open orders by exchange
            side (Side): filter open orders by side
        Returns:
            list (Order): list of open orders
        """
        # ensure has list
        if strategy not in self._strategy_past_orders:
            self._strategy_past_orders[strategy] = []

        ret = self._strategy_past_orders[strategy].copy()
        if instrument:
            ret = [r for r in ret if r.instrument == instrument]
        if exchange:
            ret = [r for r in ret if r.exchange == exchange]
        if side:
            ret = [r for r in ret if r.side == side]
        return ret

    def trades(
        self,
        strategy,
        instrument: Instrument = None,
        exchange: ExchangeType = None,
        side: Side = None,
    ):
        """select all past trades

        Args:
            instrument (Instrument): filter trades by instrument
            exchange (ExchangeType): filter trades by exchange
            side (Side): filter trades by side
        Returns:
            list (Trade): list of trades
        """
        # ensure has list
        if strategy not in self._strategy_trades:
            self._strategy_trades[strategy] = []

        ret = self._strategy_trades[strategy].copy()
        if instrument:
            ret = [r for r in ret if r.instrument == instrument]
        if exchange:
            ret = [r for r in ret if r.exchange == exchange]
        if side:
            ret = [r for r in ret if r.side == side]
        return ret

    #########################
    # Order Entry Callbacks #
    #########################
    async def onTraded(self, event: Event):
        if event in self._alerted_events:
            strategy, order = self._alerted_events[event]
            # remove from list of open orders if done
            if order.filled >= order.volume:
                self._strategy_open_orders[strategy].remove(order)
        else:
            strategy = None

        await self._portfolio_mgr.onTraded(event, strategy)
        await self._risk_mgr.onTraded(event, strategy)
        await self._order_mgr.onTraded(event, strategy)

    async def onReceived(self, event: Event):
        # synchronize state
        if event in self._alerted_events:
            strategy, order = self._alerted_events[event]
            # don't remove or do anything else
        else:
            strategy = None

        await self._portfolio_mgr.onReceived(event, strategy)
        await self._risk_mgr.onReceived(event, strategy)
        await self._order_mgr.onReceived(event, strategy)

    async def onRejected(self, event: Event):
        # synchronize state
        if event in self._alerted_events:
            strategy, order = self._alerted_events[event]
            # remove from list of open orders
            self._strategy_open_orders[strategy].remove(order)
        else:
            strategy = None

        await self._portfolio_mgr.onRejected(event, strategy)
        await self._risk_mgr.onRejected(event, strategy)
        await self._order_mgr.onRejected(event, strategy)

    async def onCanceled(self, event: Event):
        # synchronize state
        if event in self._alerted_events:
            strategy, order = self._alerted_events[event]
            # remove from list of open orders
            self._strategy_open_orders[strategy].remove(order)
        else:
            strategy = None

        await self._portfolio_mgr.onCanceled(event, strategy)
        await self._risk_mgr.onCanceled(event, strategy)
        await self._order_mgr.onCanceled(event, strategy)
