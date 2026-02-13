import logging


# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main () -> None:

	"""
	Main entry point for the subsequence module.
	"""

	logger.info("Subsequence module loaded.")
	logger.info("To run the demo, execute: python examples/demo.py")


if __name__ == "__main__":
	main()
