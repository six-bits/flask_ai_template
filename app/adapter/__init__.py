"""Adapter package."""

from app.adapter.entities import GreetingRecordEntity
from app.adapter.greeting_adapter import GreetingAdapter, greeting_adapter

__all__ = ["GreetingRecordEntity", "GreetingAdapter", "greeting_adapter"]
