import logging
from typing import TYPE_CHECKING, Any, Optional

import yfinance as yf

from rotkehlchen.assets.asset import Asset, AssetWithOracles
from rotkehlchen.constants.prices import ZERO_PRICE
from rotkehlchen.constants.timing import YEAR_IN_SECONDS
from rotkehlchen.errors.asset import UnknownAsset, UnsupportedAsset
from rotkehlchen.errors.misc import RemoteError
from rotkehlchen.errors.price import NoPriceForGivenTimestamp, PriceQueryUnsupportedAsset
from rotkehlchen.externalapis.interface import ExternalServiceWithApiKeyOptionalDB
from rotkehlchen.fval import FVal
from rotkehlchen.interfaces import HistoricalPriceOracleWithCoinListInterface
from rotkehlchen.logging import RotkehlchenLogsAdapter
from rotkehlchen.types import ExternalService, Price, Timestamp
from rotkehlchen.utils.misc import timestamp_to_date, ts_now
from rotkehlchen.utils.mixins.penalizable_oracle import PenalizablePriceOracleMixin

if TYPE_CHECKING:
    from rotkehlchen.db.dbhandler import DBHandler

logger = logging.getLogger(__name__)
log = RotkehlchenLogsAdapter(logger)


class YahooFinance(
        ExternalServiceWithApiKeyOptionalDB,
        HistoricalPriceOracleWithCoinListInterface,
        PenalizablePriceOracleMixin,
):
    """Yahoo Finance API implementation

    Using the yfinance library: https://github.com/ranaroussi/yfinance
    """

    def __init__(self, database: 'DBHandler | None') -> None:
        super().__init__(database=database, service_name=ExternalService.YAHOOFINANCE)
        self.session = None  # No session needed for yfinance
        self.penalty_until = 0
        self._symbols_cache: dict[str, Any] = {}

    def _get_symbol_for_asset(self, asset: Asset) -> str:
        """Get the Yahoo Finance symbol for an asset"""
        # For stocks and ETFs, the symbol is usually the same as the asset identifier
        # For cryptocurrencies, we need to append "-USD" to get the USD price
        if asset.identifier.startswith('yahoo:'):
            # If the asset identifier already has a yahoo: prefix, use the rest as the symbol
            return asset.identifier[6:]
        
        # For cryptocurrencies, we can try to append -USD
        if asset.is_cryptocurrency():
            return f"{asset.symbol}-USD"
        
        # For stocks and ETFs, use the symbol directly
        return asset.symbol

    def query_current_price(
            self,
            from_asset: AssetWithOracles,
            to_asset: AssetWithOracles,
    ) -> Price:
        """
        Query Yahoo Finance for the current price of an asset.
        
        Args:
            from_asset: The asset for which we want to find the price
            to_asset: The asset against which we want to find the price
            
        Returns:
            The current price of from_asset in to_asset
            
        Raises:
            RemoteError: If there is a problem with the Yahoo Finance API
            PriceQueryUnsupportedAsset: If the asset is not supported by Yahoo Finance
        """
        if self.penalty_until != 0 and ts_now() < self.penalty_until:
            raise RemoteError('Yahoo Finance API request failed')

        if to_asset.identifier != 'USD':
            # Yahoo Finance primarily provides prices in USD
            # For other quote currencies, we need to convert
            usd_price = self.query_current_price(from_asset=from_asset, to_asset=Asset('USD'))
            usd_to_to_asset = self.query_current_price(from_asset=Asset('USD'), to_asset=to_asset)
            return Price(usd_price * usd_to_to_asset)

        try:
            symbol = self._get_symbol_for_asset(from_asset)
            ticker = yf.Ticker(symbol)
            
            # Get the latest price data
            data = ticker.history(period='1d')
            
            if data.empty:
                raise PriceQueryUnsupportedAsset(from_asset.identifier)
            
            # Get the closing price from the most recent data
            price = data['Close'].iloc[-1]
            return Price(FVal(price))
        except Exception as e:
            log.error(
                f'Yahoo Finance API request failed when querying {from_asset.identifier} '
                f'price against {to_asset.identifier}',
                error=str(e),
            )
            self.penalty_until = ts_now() + 60  # Penalize for 60 seconds
            raise RemoteError(f'Yahoo Finance API request failed: {str(e)}')

    def can_query_history(
            self,
            from_asset: Asset,
            to_asset: Asset,
            timestamp: Timestamp,
            seconds: Optional[int] = None,
    ) -> bool:
        """
        Check if Yahoo Finance can provide historical price data for the given asset pair at the given timestamp.
        
        Args:
            from_asset: The asset for which we want to find the price
            to_asset: The asset against which we want to find the price
            timestamp: The timestamp at which we want to find the price
            seconds: Optional seconds to add to the timestamp
            
        Returns:
            True if Yahoo Finance can provide historical price data for the given asset pair at the given timestamp
        """
        if self.penalty_until != 0 and ts_now() < self.penalty_until:
            return False

        # Yahoo Finance has data for most stocks and ETFs going back many years
        # For cryptocurrencies, data availability varies
        # We'll be optimistic and return True, and handle failures in query_historical_price
        return True

    def query_historical_price(
            self,
            from_asset: Asset,
            to_asset: Asset,
            timestamp: Timestamp,
    ) -> Price:
        """
        Query Yahoo Finance for the historical price of an asset at a given timestamp.
        
        Args:
            from_asset: The asset for which we want to find the price
            to_asset: The asset against which we want to find the price
            timestamp: The timestamp at which we want to find the price
            
        Returns:
            The price of from_asset in to_asset at the given timestamp
            
        Raises:
            RemoteError: If there is a problem with the Yahoo Finance API
            NoPriceForGivenTimestamp: If Yahoo Finance does not have price data for the given timestamp
            PriceQueryUnsupportedAsset: If the asset is not supported by Yahoo Finance
        """
        if self.penalty_until != 0 and ts_now() < self.penalty_until:
            raise RemoteError('Yahoo Finance API request failed')

        if to_asset.identifier != 'USD':
            # Yahoo Finance primarily provides prices in USD
            # For other quote currencies, we need to convert
            usd_price = self.query_historical_price(from_asset=from_asset, to_asset=Asset('USD'), timestamp=timestamp)
            usd_to_to_asset = self.query_historical_price(from_asset=Asset('USD'), to_asset=to_asset, timestamp=timestamp)
            return Price(usd_price * usd_to_to_asset)

        try:
            symbol = self._get_symbol_for_asset(from_asset)
            ticker = yf.Ticker(symbol)
            
            # Convert timestamp to date string (YYYY-MM-DD)
            date_str = timestamp_to_date(timestamp, formatstr='%Y-%m-%d')
            
            # Get historical data for a period around the requested date
            # We'll get data for a week before and after to ensure we have the date we need
            start_date = timestamp_to_date(timestamp - YEAR_IN_SECONDS, formatstr='%Y-%m-%d')
            end_date = timestamp_to_date(timestamp + YEAR_IN_SECONDS, formatstr='%Y-%m-%d')
            
            data = ticker.history(start=start_date, end=end_date)
            
            if data.empty:
                raise PriceQueryUnsupportedAsset(from_asset.identifier)
            
            # Find the closest date to the requested timestamp
            # Yahoo Finance data is indexed by date, so we need to find the closest date
            closest_date = None
            min_diff = float('inf')
            
            for date_index in data.index:
                date_timestamp = Timestamp(int(date_index.timestamp()))
                diff = abs(date_timestamp - timestamp)
                
                if diff < min_diff:
                    min_diff = diff
                    closest_date = date_index
            
            if closest_date is None or min_diff > 86400 * 7:  # More than a week difference
                raise NoPriceForGivenTimestamp(
                    from_asset=from_asset,
                    to_asset=to_asset,
                    time=timestamp,
                    message=f"Could not find price data close to the requested timestamp",
                )
            
            price = data.loc[closest_date, 'Close']
            return Price(FVal(price))
        except NoPriceForGivenTimestamp:
            raise
        except Exception as e:
            log.error(
                f'Yahoo Finance API request failed when querying {from_asset.identifier} '
                f'price against {to_asset.identifier} at {timestamp}',
                error=str(e),
            )
            self.penalty_until = ts_now() + 60  # Penalize for 60 seconds
            raise RemoteError(f'Yahoo Finance API request failed: {str(e)}')

    def all_coins(self) -> dict[str, dict[str, Any]]:
        """
        Yahoo Finance doesn't have a comprehensive list of all available symbols.
        This method returns an empty dictionary as it's not applicable.
        """
        return {} 