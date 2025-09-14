import clr
import logging  # Import the logging module

assy = clr.AddReference("TcSoaClient")  # type: ignore
import Teamcenter.Soa.Client as TcSoaClient  # type: ignore

# Set up a logger for this module
logger = logging.getLogger(__name__)


# This implemenation of the RequestListener, logs each service request to the console.
class AppXRequestListener(TcSoaClient.RequestListener):
    __namespace__ = "PyTC_AppXRequestListener"

    # Called before each request is sent to the server.
    def ServiceRequest(self, info: TcSoaClient.ServiceInfo) -> None:
        """
        Logs information about the service request before it is sent.
        """
        if logger.isEnabledFor(logging.DEBUG):  # Or use INFO if you always want to see it
            logger.debug(f"Requesting ({info.Id}): {info.Service}.{info.Operation}")

    # Called after each response from the server.
    # Log the service operation to the console.
    def ServiceResponse(self, info: TcSoaClient.ServiceInfo) -> None:
        """
        Logs information about the service response after it is received.
        """
        if logger.isEnabledFor(logging.INFO):  # Or DEBUG if preferred
            logger.info(f"Responded  ({info.Id}): {info.Service}.{info.Operation}")
