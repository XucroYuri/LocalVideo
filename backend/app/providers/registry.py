from typing import Generic, TypeVar

from .base import (
    AudioProvider,
    DeepResearchProvider,
    ImageProvider,
    LLMProvider,
    SearchProvider,
    VideoProvider,
)

T = TypeVar("T")


class ProviderRegistry(Generic[T]):
    """Generic registry for providers"""

    def __init__(self):
        self._providers: dict[str, type[T]] = {}
        self._instances: dict[str, T] = {}

    def register(self, name: str, cls: type[T] | None = None):
        """Register a provider - can be used as decorator or direct call

        Usage as decorator:
            @registry.register("name")
            class MyProvider: ...

        Usage as direct call:
            registry.register("name", MyProvider)
        """
        if cls is not None:
            self._providers[name] = cls
            setattr(cls, "name", name)
            return cls

        def decorator(provider_cls: type[T]) -> type[T]:
            self._providers[name] = provider_cls
            setattr(provider_cls, "name", name)
            return provider_cls

        return decorator

    def get_class(self, name: str) -> type[T] | None:
        """Get provider class by name

        Args:
            name: Provider name

        Returns:
            Provider class or None if not found
        """
        return self._providers.get(name)

    def get_instance(self, name: str, **kwargs) -> T:
        """Get or create provider instance

        Args:
            name: Provider name
            **kwargs: Arguments for provider initialization

        Returns:
            Provider instance

        Raises:
            ValueError: If provider not found
        """
        key = f"{name}:{hash(frozenset(kwargs.items()))}"
        if key not in self._instances:
            cls = self._providers.get(name)
            if cls is None:
                raise ValueError(f"Provider '{name}' not found")
            self._instances[key] = cls(**kwargs)
        return self._instances[key]

    def list_providers(self) -> list[str]:
        """List all registered provider names

        Returns:
            List of provider names
        """
        return list(self._providers.keys())


llm_registry = ProviderRegistry[LLMProvider]()
search_registry = ProviderRegistry[SearchProvider]()
deep_research_registry = ProviderRegistry[DeepResearchProvider]()
audio_registry = ProviderRegistry[AudioProvider]()
image_registry = ProviderRegistry[ImageProvider]()
video_registry = ProviderRegistry[VideoProvider]()


def get_llm_provider(name: str, **kwargs) -> LLMProvider:
    return llm_registry.get_instance(name, **kwargs)


def get_search_provider(name: str, **kwargs) -> SearchProvider:
    return search_registry.get_instance(name, **kwargs)


def get_deep_research_provider(name: str, **kwargs) -> DeepResearchProvider:
    return deep_research_registry.get_instance(name, **kwargs)


def get_audio_provider(name: str, **kwargs) -> AudioProvider:
    return audio_registry.get_instance(name, **kwargs)


def get_image_provider(name: str, **kwargs) -> ImageProvider:
    return image_registry.get_instance(name, **kwargs)


def get_video_provider(name: str, **kwargs) -> VideoProvider:
    return video_registry.get_instance(name, **kwargs)
