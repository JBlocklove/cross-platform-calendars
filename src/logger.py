import logging

def setup_logging(level: str = "INFO"):
    logging.basicConfig(
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        level=getattr(logging, level.upper(), logging.INFO)
    )
