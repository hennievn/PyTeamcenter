import clr
import logging

clr.AddReference("TcSoaClient")  # type: ignore
import Teamcenter.Soa.Client as TcSoaClient  # type: ignore

# Set up a logger for this module
logger = logging.getLogger(__name__)


class AppXRequestListener(TcSoaClient.RequestListener):
    """
    An implementation of `Teamcenter.Soa.Client.RequestListener` that logs each service request and
    response to the console using the logging module.

    This listener allows the application to monitor all traffic passing through the SOA framework,
    which is invaluable for debugging and performance analysis.
    """
    __namespace__ = "PyTC_AppXRequestListener"

    def ServiceRequest(self, info: TcSoaClient.ServiceInfo) -> None:
        """
        Logs information about the service request before it is sent.
        This is called by the SOA framework for every outgoing service call.

        Args:
            info: A `ServiceInfo` object containing details about the request.
                  - `Service`: The name of the service interface (e.g., "Core-2011-06-Session").
                  - `Operation`: The method name (e.g., "login").
                  - `Id`: A unique identifier for the request/response pair.
        """
        # Use DEBUG level for requests, as they are verbose.
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(f"Requesting ({info.Id}): {info.Service}.{info.Operation}")

    def ServiceResponse(self, info: TcSoaClient.ServiceInfo) -> None:
        """
        Logs information about the service response after it is received.
        This is called by the SOA framework for every incoming service response.

        Args:
            info: A `ServiceInfo` object containing details about the response.
                  - `Service`: The name of the service interface.
                  - `Operation`: The method name.
                  - `Id`: Matches the request ID.
        """
        # Use INFO level for responses.
        if logger.isEnabledFor(logging.INFO):
            logger.info(f"Responded  ({info.Id}): {info.Service}.{info.Operation}")
