import clr
import logging

clr.AddReference("TcSoaClient")  # type: ignore
import Teamcenter.Soa.Client as TcSoaClient  # type: ignore

# Set up a logger for this module
logger = logging.getLogger(__name__)


class AppXRequestListener(TcSoaClient.RequestListener):
    """
    An implementation of RequestListener that logs each service request and
    response to the console using the logging module.
    """
    __namespace__ = "PyTC_AppXRequestListener"

    def ServiceRequest(self, info: TcSoaClient.ServiceInfo) -> None:
        """
        Logs information about the service request before it is sent.
        This is called by the SOA framework for every outgoing service call.

        Args:
            info: A ServiceInfo object containing details about the request.
        """
        # Use DEBUG level for requests, as they are verbose.
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(f"Requesting ({info.Id}): {info.Service}.{info.Operation}")

    def ServiceResponse(self, info: TcSoaClient.ServiceInfo) -> None:
        """
        Logs information about the service response after it is received.
        This is called by the SOA framework for every incoming service response.

        Args:
            info: A ServiceInfo object containing details about the response.
        """
        # Use INFO level for responses.
        if logger.isEnabledFor(logging.INFO):
            logger.info(f"Responded  ({info.Id}): {info.Service}.{info.Operation}")
