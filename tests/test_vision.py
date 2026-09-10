import pytest

from pokehunt.config import VisionConfig
from pokehunt.vision.identify import VisionIdentifier
from pokehunt.vision.schema import IDENTIFY_TOOL, CardIdentity, LotIdentification


class Block:
    def __init__(self, type_, input_=None):
        self.type = type_
        self.input = input_ or {}


class Response:
    def __init__(self, content):
        self.content = content


class FakeMessages:
    def __init__(self, behaviour):
        self.behaviour = behaviour
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        result = self.behaviour[min(len(self.calls) - 1, len(self.behaviour) - 1)]
        if isinstance(result, Exception):
            raise result
        return result


class FakeAnthropic:
    def __init__(self, behaviour):
        self.messages = FakeMessages(behaviour)


PAYLOAD = {
    "cards": [
        {"name": "Charizard", "set_name": "Base Set", "card_number": "4/102",
         "variant": "holofoil", "condition_estimate": "lightly_played",
         "quantity": 1, "confidence": 0.88, "image_index": 0, "notes": None},
        {"name": "Pikachu", "quantity": 3, "confidence": 0.42, "image_index": 2},
    ],
    "lot_summary": {"total_cards_visible": 40, "identified_fraction": 0.1,
                    "obstructions": "cards are stacked face down"},
}


@pytest.mark.asyncio
async def test_identify_parses_the_tool_call():
    client = FakeAnthropic([Response([Block("tool_use", PAYLOAD)])])
    identifier = VisionIdentifier(VisionConfig(api_key="k", model="m"), client)

    result = await identifier.identify(["https://img/1.jpg", "https://img/2.jpg"], "a lot")

    assert [c.name for c in result.cards] == ["Charizard", "Pikachu"]
    assert result.cards[0].card_number == "4/102"
    assert result.cards[1].quantity == 3
    assert result.min_confidence == pytest.approx(0.42)
    assert result.obstructions == "cards are stacked face down"
    assert result.error is None


@pytest.mark.asyncio
async def test_identify_forces_the_tool_and_sends_every_photo():
    client = FakeAnthropic([Response([Block("tool_use", PAYLOAD)])])
    identifier = VisionIdentifier(VisionConfig(api_key="k", model="m"), client)

    await identifier.identify([f"https://img/{i}.jpg" for i in range(3)], "title")

    call = client.messages.calls[0]
    assert call["tool_choice"] == {"type": "tool", "name": "report_cards"}
    assert call["tools"] == [IDENTIFY_TOOL]
    content = call["messages"][0]["content"]
    images = [b for b in content if b["type"] == "image"]
    assert [b["source"]["url"] for b in images] == [f"https://img/{i}.jpg" for i in range(3)]
    # The title goes in as an explicitly untrusted hint.
    assert "unreliable hint" in content[-1]["text"]


@pytest.mark.asyncio
async def test_identify_caps_the_number_of_photos():
    client = FakeAnthropic([Response([Block("tool_use", PAYLOAD)])])
    identifier = VisionIdentifier(VisionConfig(api_key="k", model="m"), client)

    await identifier.identify([f"https://img/{i}.jpg" for i in range(20)], "t", max_images=3)

    content = client.messages.calls[0]["messages"][0]["content"]
    assert len([b for b in content if b["type"] == "image"]) == 3


@pytest.mark.asyncio
async def test_identify_retries_then_reports_the_error():
    client = FakeAnthropic([RuntimeError("overloaded")])
    identifier = VisionIdentifier(VisionConfig(api_key="k", model="m"), client)

    result = await identifier.identify(["https://img/1.jpg"], "t", retries=1)

    assert len(client.messages.calls) == 2
    assert result.cards == []
    assert "overloaded" in result.error


@pytest.mark.asyncio
async def test_identify_recovers_on_the_second_attempt():
    client = FakeAnthropic([RuntimeError("transient"), Response([Block("tool_use", PAYLOAD)])])
    identifier = VisionIdentifier(VisionConfig(api_key="k", model="m"), client)

    result = await identifier.identify(["https://img/1.jpg"], "t", retries=2)
    assert result.error is None and len(result.cards) == 2


@pytest.mark.asyncio
async def test_a_listing_with_no_photos_is_an_error_not_an_empty_lot():
    client = FakeAnthropic([Response([Block("tool_use", PAYLOAD)])])
    identifier = VisionIdentifier(VisionConfig(api_key="k", model="m"), client)

    result = await identifier.identify([], "t")
    assert result.error == "no images on listing"
    assert client.messages.calls == []


@pytest.mark.asyncio
async def test_text_only_response_is_treated_as_a_failure():
    client = FakeAnthropic([Response([Block("text")])])
    identifier = VisionIdentifier(VisionConfig(api_key="k", model="m"), client)

    result = await identifier.identify(["https://img/1.jpg"], "t")
    assert "no tool_use block" in result.error


def test_confidence_aggregates_weight_by_quantity():
    lot = LotIdentification(cards=[
        CardIdentity(name="A", quantity=1, confidence=1.0, image_index=0),
        CardIdentity(name="B", quantity=3, confidence=0.0, image_index=0),
    ])
    assert lot.min_confidence == 0.0
    assert lot.mean_confidence == pytest.approx(0.25)


def test_schema_requires_confidence_on_every_card():
    card_schema = IDENTIFY_TOOL["input_schema"]["properties"]["cards"]["items"]
    assert "confidence" in card_schema["required"]
    assert card_schema["properties"]["confidence"]["maximum"] == 1
