import base64
import json
import logging

import boto3
from playwright.async_api import Locator, Page

logger = logging.getLogger("batch_validator")


class VLMFallback:
    def __init__(
        self, region: str = "us-east-1", model: str = "us.anthropic.claude-sonnet-4-6-20250514-v1:0"
    ):
        self.client = boto3.client("bedrock-runtime", region_name=region)
        self.model = model

    async def read_element(self, page: Page, locator: Locator, context: str = "") -> str | None:
        try:
            screenshot = await locator.screenshot(type="png")
        except Exception:
            try:
                screenshot = await page.screenshot(type="png", full_page=False)
            except Exception as e:
                logger.warning(f"VLM fallback screenshot failed: {e}")
                return None

        encoded = base64.b64encode(screenshot).decode("utf-8")

        prompt = "Read the text content visible in this screenshot. Return ONLY the text you can see — no explanation, no formatting."
        if context:
            prompt += f" Context: this should be a {context}."

        try:
            response = self.client.invoke_model(
                modelId=self.model,
                body=json.dumps(
                    {
                        "anthropic_version": "bedrock-2023-05-31",
                        "max_tokens": 200,
                        "temperature": 0,
                        "messages": [
                            {
                                "role": "user",
                                "content": [
                                    {
                                        "type": "image",
                                        "source": {
                                            "type": "base64",
                                            "media_type": "image/png",
                                            "data": encoded,
                                        },
                                    },
                                    {"type": "text", "text": prompt},
                                ],
                            }
                        ],
                    }
                ),
                contentType="application/json",
            )
            body = json.loads(response["body"].read())
            text = body["content"][0]["text"].strip()
            logger.info(f"VLM fallback read: '{text[:50]}...'")
            return text
        except Exception as e:
            logger.warning(f"VLM fallback API call failed: {e}")
            return None
