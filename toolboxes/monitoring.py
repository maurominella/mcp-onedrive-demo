import os
import logging
from dotenv import load_dotenv
load_dotenv()  # MUST be first: env vars must be set before any import reads them

THISAPP_NAME = "mcp-onedrive-demo01"

 
# --- Azure Monitor setup ---------------------------------------------------
# We configure Azure Monitor OURSELVES at INFO level so our logger.info() traces
# reach Application Insights. The agentserver runtime also configures OpenTelemetry
# internally, so the double setup may emit two harmless one-time startup warnings:
#   "Overriding of current LoggerProvider is not allowed"
#   "Overriding of current TracerProvider is not allowed"
# These are cosmetic only: they fire once at startup and do not affect runtime.
# In Application Insights Logs, you can filter for our logs with:
# traces
# | where cloud_RoleName == "THISAPP_NAME"
if os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING"):
    # Give this app a distinct cloud role name so ALL its telemetry (traces, requests,
    # dependencies) is stamped with cloud_RoleName == this value. This is what lets you
    # isolate it in a shared Application Insights resource (e.g. away from APIM noise).
    # Must be set BEFORE configure_azure_monitor() reads the environment.
    os.environ.setdefault("OTEL_SERVICE_NAME", THISAPP_NAME)  # e.g. "hello-world-python-responses"

    from azure.monitor.opentelemetry import configure_azure_monitor
    configure_azure_monitor(logging_level=logging.INFO)  # capture INFO+ in App Insights (default is WARNING)


# Configure logging - WARNING for everything else, while INFO for this module only
logging.basicConfig(level=logging.WARNING)  # "father" logger at WARNING to avoid noise from other modules
logger = logging.getLogger(__name__)        # "child" logger for this module
logger.setLevel(logging.INFO)               # INFO for more detailed logs from our module

class _AppLogFilter(logging.Filter):
    """Stamp every record from OUR logger with a custom dimension so it can be
    isolated in Application Insights, independently of severity level.
    In App Insights it lands in customDimensions['log_source'] == 'app'."""
    def filter(self, record: logging.LogRecord) -> bool:
        record.log_source = "app"
        return True

logger.addFilter(_AppLogFilter())           # only records going through THIS logger get tagged

if not logger.handlers:                     # avoid duplicate handlers on reload
    _handler = logging.StreamHandler()
    _handler.setLevel(logging.INFO)
    logger.addHandler(_handler)
    logger.propagate = True                 # (default) so logs also reach the root logger

if os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING"):
    logger.info("Azure Monitor is active.")
else:
    logger.info("Azure Monitor is not configured. No connection string found in environment variables.")