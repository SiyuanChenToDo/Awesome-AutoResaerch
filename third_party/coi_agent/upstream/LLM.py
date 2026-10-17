from openai import AzureOpenAI, OpenAI,AsyncAzureOpenAI,AsyncOpenAI
from abc import abstractmethod
import os
import httpx
import base64
import logging
import asyncio
import numpy as np
from tenacity import (
    retry,
    stop_after_attempt,
    wait_fixed,
)


def get_content_between_a_b(start_tag, end_tag, text):
    extracted_text = ""
    start_index = text.find(start_tag)
    while start_index != -1:
        end_index = text.find(end_tag, start_index + len(start_tag))
        if end_index != -1:
            extracted_text += text[start_index + len(start_tag) : end_index] + " "
            start_index = text.find(start_tag, end_index + len(end_tag))
        else:
            break

    return extracted_text.strip()

def before_retry_fn(retry_state):
    if retry_state.attempt_number > 1:
        logging.info(f"Retrying API call. Attempt #{retry_state.attempt_number}, f{retry_state}")

def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

def get_openai_url(img_pth):
    end = img_pth.split(".")[-1]
    if end == "jpg":
        end = "jpeg"
    base64_image = encode_image(img_pth)
    return f"data:image/{end};base64,{base64_image}"

class base_llm:
    def __init__(self) -> None:
        pass
    
    @abstractmethod
    def response(self,messages,**kwargs):
        pass


class openai_llm(base_llm):
    def __init__(self,model = "gpt4o-0513") -> None:
        super().__init__()
        is_azure = os.environ.get("is_azure", True)
        self.model = model

        if is_azure:
            if "AZURE_OPENAI_ENDPOINT" not in os.environ or os.environ["AZURE_OPENAI_ENDPOINT"] == "":
                raise ValueError("AZURE_OPENAI_ENDPOINT is not set")
            if "AZURE_OPENAI_KEY" not in os.environ or os.environ["AZURE_OPENAI_KEY"] == "":
                raise ValueError("AZURE_OPENAI_KEY is not set")
            
            api_version = os.environ.get("AZURE_OPENAI_API_VERSION",None)
            if api_version == "":
                api_version = None
            self.client = AzureOpenAI(
                azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
                api_key=os.environ["AZURE_OPENAI_KEY"],
                api_version= api_version
                )
            self.async_client = AsyncAzureOpenAI(
                azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
                api_key=os.environ["AZURE_OPENAI_KEY"],
                api_version= api_version
                )

        else:
            if "OPENAI_API_KEY" not in os.environ or os.environ["OPENAI_API_KEY"] == "":
                raise ValueError("OPENAI_API_KEY is not set")
            
            api_key = os.environ.get("OPENAI_API_KEY",None)
            proxy_url = os.environ.get("OPENAI_PROXY_URL", None)
            if proxy_url == "":
                proxy_url = None
            base_url = os.environ.get("OPENAI_BASE_URL", None)
            if base_url == "":
                base_url = None
            http_client = httpx.Client(proxy=proxy_url) if proxy_url else None
            async_http_client = httpx.AsyncClient(proxy=proxy_url) if proxy_url else None

            self.client = OpenAI(api_key=api_key,base_url=base_url,http_client=http_client)

            self.async_client = AsyncOpenAI(api_key=api_key,base_url=base_url,http_client=async_http_client)
    
    def cal_cosine_similarity(self, vec1, vec2):
        if isinstance(vec1, list):
            vec1 = np.array(vec1)
        if isinstance(vec2, list):
            vec2 = np.array(vec2)
        return np.dot(vec1, vec2) / (np.linalg.norm(vec1) * np.linalg.norm(vec2))
    
    
    @retry(wait=wait_fixed(10), stop=stop_after_attempt(10), before=before_retry_fn)
    def response(self,messages,**kwargs):
        try:
            response = self.client.chat.completions.create(
                model=kwargs.get("model", self.model),
                messages=messages,
                n = kwargs.get("n", 1),
                temperature= kwargs.get("temperature", 0.7),
                max_tokens=kwargs.get("max_tokens", 4000),
                timeout=kwargs.get("timeout", 180)
            )
        except Exception as e:
            model = kwargs.get("model", self.model)
            print(f"get {model} response failed: {e}")
            print(e)
            logging.info(e)
            return
        return response.choices[0].message.content
    
    @retry(wait=wait_fixed(10), stop=stop_after_attempt(10), before=before_retry_fn)
    def get_embbeding(self,text):
        if os.environ.get("EMBEDDING_API_ENDPOINT"):
            client = AzureOpenAI(
            azure_endpoint=os.environ.get("EMBEDDING_API_ENDPOINT",None),
            api_key=os.environ.get("EMBEDDING_API_KEY",None),
            api_version= os.environ.get("AZURE_OPENAI_API_VERSION",None),
            azure_deployment="embedding-3-large"
            )
        else:
            client = self.client
        try:
            embbeding = client.embeddings.create(
                model=os.environ.get("EMBEDDING_MODEL","text-embedding-3-large"),
                input=text,
                timeout= 180
            )
            embbeding = embbeding.data
            if len(embbeding) == 0:
                return None
            elif len(embbeding) == 1:
                return embbeding[0].embedding
            else:
                return [e.embedding for e in embbeding]
        except Exception as e:
            print(f"get embbeding failed: {e}")
            print(e)
            logging.info(e)
            return
    
    @retry(wait=wait_fixed(10), stop=stop_after_attempt(10), before=before_retry_fn)
    async def get_embbeding_async(self,text):
        if os.environ.get("EMBEDDING_API_ENDPOINT"):
            client = AsyncAzureOpenAI(
            azure_endpoint=os.environ.get("EMBEDDING_API_ENDPOINT",None),
            api_key=os.environ.get("EMBEDDING_API_KEY",None),
            api_version= os.environ.get("AZURE_OPENAI_API_VERSION",None),
            azure_deployment="embedding-3-large"
            )
        else:
            client = self.async_client
        try:
            embbeding = await client.embeddings.create(
                model=os.environ.get("EMBEDDING_MODEL","text-embedding-3-large"),
                input=text,
                timeout= 180
            )
            embbeding = embbeding.data
            if len(embbeding) == 0:
                return None
            elif len(embbeding) == 1:
                return embbeding[0].embedding
            else:
                return [e.embedding for e in embbeding]
        except Exception as e:
            print(f"get embbeding failed: {e}")
            print(e)
            logging.info(e)
            return
    
    @retry(wait=wait_fixed(10), stop=stop_after_attempt(10), before=before_retry_fn)
    async def response_async(self,messages,**kwargs):
        try:
            response = await self.async_client.chat.completions.create(
                model=kwargs.get("model", self.model),
                messages=messages,
                n = kwargs.get("n", 1),
                temperature= kwargs.get("temperature", 0.7),
                max_tokens=kwargs.get("max_tokens", 4000),
                timeout=kwargs.get("timeout", 180)
            )
        except Exception as e:
            await asyncio.sleep(0.1)
            model = kwargs.get("model", self.model)
            print(f"get {model} response failed: {e}")
            print(e)
            logging.info(e)
            return

        return response.choices[0].message.content

