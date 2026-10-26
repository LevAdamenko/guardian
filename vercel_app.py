"""Vercel entry point: the public demo is replay-only and never calls Nemotron or Tavily."""
import os

# Set before guardian reads its config: process env wins over any secrets file, so no
# project env var can switch the hosted demo to LIVE and spend provider credits.
os.environ["LIVE"] = "0"

from guardian.app import app  # noqa: E402

__all__ = ["app"]
