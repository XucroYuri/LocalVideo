from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass


@dataclass
class LLMResponse:
    """Response from LLM provider"""

    content: str
    model: str
    usage: dict | None = None


class LLMProvider(ABC):
    """Base class for LLM providers"""

    name: str = "base_llm"

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        image_url: str | None = None,
        image_base64: str | None = None,
    ) -> LLMResponse:
        """Generate text completion

        Args:
            prompt: The user prompt
            system_prompt: Optional system prompt to set context
            temperature: Sampling temperature (0.0 to 1.0)
            max_tokens: Maximum tokens to generate
            image_url: Optional URL of an image for vision tasks
            image_base64: Optional base64-encoded image data for vision tasks

        Returns:
            LLMResponse with generated content
        """
        pass

    @abstractmethod
    async def generate_stream(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        image_url: str | None = None,
        image_base64: str | None = None,
    ) -> AsyncIterator[str]:
        """Generate text completion with streaming

        Args:
            prompt: The user prompt
            system_prompt: Optional system prompt to set context
            temperature: Sampling temperature (0.0 to 1.0)
            max_tokens: Maximum tokens to generate
            image_url: Optional URL of an image for vision tasks
            image_base64: Optional base64-encoded image data for vision tasks

        Yields:
            Text chunks as they are generated
        """
        pass

    @abstractmethod
    async def generate_json(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.3,
    ) -> dict:
        """Generate JSON response

        Args:
            prompt: The user prompt
            system_prompt: Optional system prompt to set context
            temperature: Sampling temperature (0.0 to 1.0)

        Returns:
            Parsed JSON response as dictionary
        """
        pass
