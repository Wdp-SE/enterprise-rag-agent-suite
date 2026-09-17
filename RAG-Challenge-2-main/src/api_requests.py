import os
import json
from dotenv import load_dotenv
from typing import Union, List, Dict, Type, Optional, Literal
from openai import OpenAI
import asyncio
from openai.lib._parsing import type_to_response_format_param 
import src.prompts as prompts
import requests
from pydantic import BaseModel
from copy import deepcopy
from tenacity import retry, stop_after_attempt, wait_fixed
from src.provider_config import normalize_provider, resolve_provider_model

try:
    import tiktoken
except ImportError:
    tiktoken = None

try:
    from json_repair import repair_json
except ImportError:  # Keep non-repairing providers importable in minimal test environments.
    def repair_json(value):
        return value

try:
    import google.generativeai as genai
except ImportError:  # Loaded only when the Gemini provider is selected.
    genai = None

try:
    import dashscope
except ImportError:  # Loaded only when the DashScope provider is selected.
    dashscope = None


def parse_structured_response(content, response_format: Type[BaseModel]) -> Dict:
    """Parse model JSON text and validate it against a Pydantic response model."""
    if response_format is None:
        raise ValueError("response_format is required for structured output.")

    if isinstance(content, BaseModel):
        parsed = content.model_dump()
    elif isinstance(content, dict):
        parsed = content
    elif isinstance(content, str):
        cleaned = content.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.removeprefix("```json").removeprefix("```JSON")
            cleaned = cleaned.removeprefix("```")
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError:
            try:
                parsed = json.loads(repair_json(cleaned))
            except Exception as err:
                raise ValueError("Model response is not valid structured JSON.") from err
    else:
        raise TypeError(f"Unsupported structured response type: {type(content).__name__}.")

    if not isinstance(parsed, dict):
        raise ValueError("Structured model response must be a JSON object.")
    return response_format.model_validate(parsed).model_dump()

# OpenAI基础处理器，封装了消息发送、结构化输出、计费等逻辑
class BaseOpenaiProcessor:
    def __init__(self):
        self.llm = self.set_up_llm()
        self.default_model = 'gpt-4o-2024-08-06'
        # self.default_model = 'gpt-4o-mini-2024-07-18',

    def set_up_llm(self):
        # 加载OpenAI API密钥，初始化LLM
        load_dotenv()
        llm = OpenAI(
            api_key=os.getenv("OPENAI_API_KEY"),
            timeout=None,
            max_retries=2
            )
        return llm

    def send_message(
        self,
        model=None,
        temperature=0.5,
        seed=None, # For deterministic ouptputs
        system_content='You are a helpful assistant.',
        human_content='Hello!',
        is_structured=False,
        response_format=None
        ):
        # 发送消息到OpenAI，支持结构化/非结构化输出
        if model is None:
            model = self.default_model
        params = {
            "model": model,
            "seed": seed,
            "messages": [
                {"role": "system", "content": system_content},
                {"role": "user", "content": human_content}
            ]
        }
        
        # 部分模型不支持temperature
        if "o3-mini" not in model:
            params["temperature"] = temperature
            
        if not is_structured:
            completion = self.llm.chat.completions.create(**params)
            content = completion.choices[0].message.content

        elif is_structured:
            params["response_format"] = response_format
            completion = self.llm.beta.chat.completions.parse(**params)

            response = completion.choices[0].message.parsed
            content = response.dict()

        self.response_data = {"model": completion.model, "input_tokens": completion.usage.prompt_tokens, "output_tokens": completion.usage.completion_tokens}
        print(self.response_data)

        return content

    @staticmethod
    def count_tokens(string, encoding_name="o200k_base"):
        # 统计字符串的token数
        if tiktoken is None:
            raise ImportError("Token counting requires the 'tiktoken' package.")
        encoding = tiktoken.get_encoding(encoding_name)
        # Encode the string and count the tokens
        tokens = encoding.encode(string)
        token_count = len(tokens)
        return token_count


# IBM API基础处理器，支持余额查询、模型列表、嵌入、消息发送等
class BaseIBMAPIProcessor:
    def __init__(self):
        load_dotenv()
        self.api_token = os.getenv("IBM_API_KEY")
        self.base_url = "https://rag.timetoact.at/ibm"
        self.default_model = 'meta-llama/llama-3-3-70b-instruct'
    def check_balance(self):
        """查询当前API余额"""
        balance_url = f"{self.base_url}/balance"
        headers = {"Authorization": f"Bearer {self.api_token}"}
        
        try:
            response = requests.get(balance_url, headers=headers)
            response.raise_for_status()
            return response.json()
        except requests.HTTPError as err:
            print(f"Error checking balance: {err}")
            return None
    
    def get_available_models(self):
        """获取可用基础模型列表"""
        models_url = f"{self.base_url}/foundation_model_specs"
        
        try:
            response = requests.get(models_url)
            response.raise_for_status()
            return response.json()
        except requests.HTTPError as err:
            print(f"Error getting available models: {err}")
            return None
    
    def get_embeddings(self, texts, model_id="ibm/granite-embedding-278m-multilingual"):
        """获取文本的向量嵌入"""
        embeddings_url = f"{self.base_url}/embeddings"
        headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json"
        }
        payload = {
            "inputs": texts,
            "model_id": model_id
        }
        
        try:
            response = requests.post(embeddings_url, headers=headers, json=payload)
            response.raise_for_status()
            return response.json()
        except requests.HTTPError as err:
            print(f"Error getting embeddings: {err}")
            return None
    
    def send_message(
        self,
        # model='meta-llama/llama-3-1-8b-instruct',
        model=None,
        temperature=0.5,
        seed=None,  # For deterministic outputs
        system_content='You are a helpful assistant.',
        human_content='Hello!',
        is_structured=False,
        response_format=None,
        max_new_tokens=5000,
        min_new_tokens=1,
        **kwargs
    ):
        # 发送消息到IBM API，支持结构化/非结构化输出
        if model is None:
            model = self.default_model
        text_generation_url = f"{self.base_url}/text_generation"
        headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json"
        }
        
        # Prepare the input messages
        input_messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": human_content}
        ]
        
        # Prepare parameters with defaults and any additional parameters
        parameters = {
            "temperature": temperature,
            "random_seed": seed,
            "max_new_tokens": max_new_tokens,
            "min_new_tokens": min_new_tokens,
            **kwargs
        }
        
        payload = {
            "input": input_messages,
            "model_id": model,
            "parameters": parameters
        }
        
        try:
            response = requests.post(text_generation_url, headers=headers, json=payload)
            response.raise_for_status()
            completion = response.json()

            content = completion.get("results")[0].get("generated_text")
            self.response_data = {"model": completion.get("model_id"), "input_tokens": completion.get("results")[0].get("input_token_count"), "output_tokens": completion.get("results")[0].get("generated_token_count")}
            print(self.response_data)
            if is_structured and response_format is not None:
                try:
                    repaired_json = repair_json(content)
                    parsed_dict = json.loads(repaired_json)
                    validated_data = response_format.model_validate(parsed_dict)
                    content = validated_data.model_dump()
                    return content
                
                except Exception as err:
                    print("Error processing structured response, attempting to reparse the response...")
                    reparsed = self._reparse_response(content, system_content)
                    try:
                        repaired_json = repair_json(reparsed)
                        reparsed_dict = json.loads(repaired_json)
                        try:
                            validated_data = response_format.model_validate(reparsed_dict)
                            print("Reparsing successful!")
                            content = validated_data.model_dump()
                            return content
                        
                        except Exception:
                            return reparsed_dict
                        
                    except Exception as reparse_err:
                        print(f"Reparse failed with error type: {type(reparse_err).__name__}")
                        return content
            
            return content

        except requests.HTTPError as err:
            print(f"Error generating text: {err}")
            return None

    def _reparse_response(self, response, system_content):

        user_prompt = prompts.AnswerSchemaFixPrompt.user_prompt.format(
            system_prompt=system_content,
            response=response
        )
        
        reparsed_response = self.send_message(
            system_content=prompts.AnswerSchemaFixPrompt.system_prompt,
            human_content=user_prompt,
            is_structured=False
        )
        
        return reparsed_response

     
class BaseGeminiProcessor:
    def __init__(self):
        self.llm = self._set_up_llm()
        self.default_model = 'gemini-2.0-flash-001'
        # self.default_model = "gemini-2.0-flash-thinking-exp-01-21",
        
    def _set_up_llm(self):
        load_dotenv()
        if genai is None:
            raise ImportError("Gemini provider requires the 'google-generativeai' package.")
        api_key = os.getenv("GEMINI_API_KEY")
        genai.configure(api_key=api_key)
        return genai

    def list_available_models(self) -> None:
        """
        Prints available Gemini models that support text generation.
        """
        print("Available models for text generation:")
        for model in self.llm.list_models():
            if "generateContent" in model.supported_generation_methods:
                print(f"- {model.name}")
                print(f"  Input token limit: {model.input_token_limit}")
                print(f"  Output token limit: {model.output_token_limit}")
                print()

    def _log_retry_attempt(retry_state):
        """Print information about the retry attempt"""
        exception = retry_state.outcome.exception()
        print(f"\nAPI Error encountered: {str(exception)}")
        print("Waiting 20 seconds before retry...\n")

    @retry(
        wait=wait_fixed(20),
        stop=stop_after_attempt(3),
        before_sleep=_log_retry_attempt,
    )
    def _generate_with_retry(self, model, human_content, generation_config):
        """Wrapper for generate_content with retry logic"""
        try:
            return model.generate_content(
                human_content,
                generation_config=generation_config
            )
        except Exception as e:
            if getattr(e, '_attempt_number', 0) == 3:
                print(f"\nRetry failed. Error: {str(e)}\n")
            raise

    def _parse_structured_response(self, response_text, response_format):
        try:
            repaired_json = repair_json(response_text)
            parsed_dict = json.loads(repaired_json)
            validated_data = response_format.model_validate(parsed_dict)
            return validated_data.model_dump()
        except Exception as err:
            print(f"Error parsing structured response: {type(err).__name__}")
            print("Attempting to reparse the response...")
            reparsed = self._reparse_response(response_text, response_format)
            return reparsed

    def _reparse_response(self, response, response_format):
        """Reparse invalid JSON responses using the model itself."""
        user_prompt = prompts.AnswerSchemaFixPrompt.user_prompt.format(
            system_prompt=prompts.AnswerSchemaFixPrompt.system_prompt,
            response=response
        )
        
        try:
            reparsed_response = self.send_message(
                model="gemini-2.0-flash-001",
                system_content=prompts.AnswerSchemaFixPrompt.system_prompt,
                human_content=user_prompt,
                is_structured=False
            )
            
            try:
                repaired_json = repair_json(reparsed_response)
                reparsed_dict = json.loads(repaired_json)
                try:
                    validated_data = response_format.model_validate(reparsed_dict)
                    print("Reparsing successful!")
                    return validated_data.model_dump()
                except Exception:
                    return reparsed_dict
            except Exception as reparse_err:
                print(f"Reparse failed with error type: {type(reparse_err).__name__}")
                return response
        except Exception as e:
            print(f"Reparse attempt failed: {e}")
            return response

    def send_message(
        self,
        model=None,
        temperature: float = 0.5,
        seed=12345,  # For back compatibility
        system_content: str = "You are a helpful assistant.",
        human_content: str = "Hello!",
        is_structured: bool = False,
        response_format: Optional[Type[BaseModel]] = None,
    ) -> Union[str, Dict, None]:
        if model is None:
            model = self.default_model

        generation_config = {"temperature": temperature}
        
        prompt = f"{system_content}\n\n---\n\n{human_content}"

        model_instance = self.llm.GenerativeModel(
            model_name=model,
            generation_config=generation_config
        )

        try:
            response = self._generate_with_retry(model_instance, prompt, generation_config)

            self.response_data = {
                "model": response.model_version,
                "input_tokens": response.usage_metadata.prompt_token_count,
                "output_tokens": response.usage_metadata.candidates_token_count
            }
            print(self.response_data)
            
            if is_structured and response_format is not None:
                return self._parse_structured_response(response.text, response_format)
            
            return response.text
        except Exception as e:
            raise Exception(f"API request failed after retries: {str(e)}")


class APIProcessor:
    def __init__(
        self,
        provider: Literal["openai", "ibm", "gemini", "dashscope"] = "dashscope",
        capability: Literal["answer", "rerank"] = "answer",
    ):
        self.provider = normalize_provider(provider)
        self.capability = capability
        if self.provider == "openai":
            self.processor = BaseOpenaiProcessor()
        elif self.provider == "ibm":
            self.processor = BaseIBMAPIProcessor()
        elif self.provider == "gemini":
            self.processor = BaseGeminiProcessor()
        elif self.provider == "dashscope":
            self.processor = BaseDashscopeProcessor()
        else:
            raise ValueError(f"Unsupported API provider: {provider}")

    def send_message(
        self,
        model=None,
        temperature=0.5,
        seed=None,
        system_content="You are a helpful assistant.",
        human_content="Hello!",
        is_structured=False,
        response_format=None,
        **kwargs
    ):
        """
        Routes the send_message call to the appropriate processor.
        The underlying processor's send_message method is responsible for handling the parameters.
        """
        _, model = resolve_provider_model(
            provider=self.provider,
            model=model or self.processor.default_model,
            capability=self.capability,
        )
        return self.processor.send_message(
            model=model,
            temperature=temperature,
            seed=seed,
            system_content=system_content,
            human_content=human_content,
            is_structured=is_structured,
            response_format=response_format,
            **kwargs
        )

    def get_answer_from_rag_context(
        self, question, rag_context, schema, model, prompt_mode="legacy_company"
    ):
        system_prompt, response_format, user_prompt = self._build_rag_context_prompts(
            schema, prompt_mode=prompt_mode
        )
        
        answer_dict = self.send_message(
            model=model,
            system_content=system_prompt,
            human_content=user_prompt.format(context=rag_context, question=question),
            is_structured=True,
            response_format=response_format
        )
        self.response_data = self.processor.response_data
        # 假如 answer_dict 只有 final_answer，自动兜底
        if 'step_by_step_analysis' not in answer_dict:
            answer_dict = {
                "step_by_step_analysis": "",
                "reasoning_summary": "",
                "relevant_pages": [],
                "relevant_sources": [],
                "final_answer": answer_dict.get("final_answer", "N/A")
            }
        return answer_dict


    def _build_rag_context_prompts(self, schema, prompt_mode="legacy_company"):
        """Return prompts tuple for the given schema."""
        if prompt_mode == "generic":
            generic_schemas = {
                "text": prompts.GenericRAGPrompt.TextAnswerSchema,
                "name": prompts.GenericRAGPrompt.TextAnswerSchema,
                "comparative": prompts.GenericRAGPrompt.TextAnswerSchema,
                "number": prompts.GenericRAGPrompt.NumberAnswerSchema,
                "boolean": prompts.GenericRAGPrompt.BooleanAnswerSchema,
                "names": prompts.GenericRAGPrompt.NamesAnswerSchema,
            }
            try:
                response_format = generic_schemas[schema]
            except KeyError as exc:
                raise ValueError(f"Unsupported schema: {schema}") from exc
            use_schema_prompt = self.provider in {"ibm", "gemini"}
            pydantic_schema = (
                json.dumps(response_format.model_json_schema(), ensure_ascii=False)
                if use_schema_prompt else ""
            )
            system_prompt = (
                prompts.build_system_prompt(
                    prompts.GenericRAGPrompt.instruction,
                    pydantic_schema=pydantic_schema,
                )
                if use_schema_prompt
                else prompts.GenericRAGPrompt.instruction.strip()
            )
            return system_prompt, response_format, prompts.GenericRAGPrompt.user_prompt
        if prompt_mode != "legacy_company":
            raise ValueError(f"Unsupported prompt mode: {prompt_mode}")

        use_schema_prompt = True if self.provider == "ibm" or self.provider == "gemini" else False
        
        if schema == "name":
            system_prompt = (prompts.AnswerWithRAGContextNamePrompt.system_prompt_with_schema 
                            if use_schema_prompt else prompts.AnswerWithRAGContextNamePrompt.system_prompt)
            response_format = prompts.AnswerWithRAGContextNamePrompt.AnswerSchema
            user_prompt = prompts.AnswerWithRAGContextNamePrompt.user_prompt
        elif schema == "number":
            system_prompt = (prompts.AnswerWithRAGContextNumberPrompt.system_prompt_with_schema
                            if use_schema_prompt else prompts.AnswerWithRAGContextNumberPrompt.system_prompt)
            response_format = prompts.AnswerWithRAGContextNumberPrompt.AnswerSchema
            user_prompt = prompts.AnswerWithRAGContextNumberPrompt.user_prompt
        elif schema == "boolean":
            system_prompt = (prompts.AnswerWithRAGContextBooleanPrompt.system_prompt_with_schema
                            if use_schema_prompt else prompts.AnswerWithRAGContextBooleanPrompt.system_prompt)
            response_format = prompts.AnswerWithRAGContextBooleanPrompt.AnswerSchema
            user_prompt = prompts.AnswerWithRAGContextBooleanPrompt.user_prompt
        elif schema == "names":
            system_prompt = (prompts.AnswerWithRAGContextNamesPrompt.system_prompt_with_schema
                            if use_schema_prompt else prompts.AnswerWithRAGContextNamesPrompt.system_prompt)
            response_format = prompts.AnswerWithRAGContextNamesPrompt.AnswerSchema
            user_prompt = prompts.AnswerWithRAGContextNamesPrompt.user_prompt
        elif schema == "comparative":
            system_prompt = (prompts.ComparativeAnswerPrompt.system_prompt_with_schema
                            if use_schema_prompt else prompts.ComparativeAnswerPrompt.system_prompt)
            response_format = prompts.ComparativeAnswerPrompt.AnswerSchema
            user_prompt = prompts.ComparativeAnswerPrompt.user_prompt
        else:
            raise ValueError(f"Unsupported schema: {schema}")
        return system_prompt, response_format, user_prompt

    def get_rephrased_questions(self, original_question: str, companies: List[str]) -> Dict[str, str]:
        """Use LLM to break down a comparative question into individual questions."""
        answer_dict = self.send_message(
            system_content=prompts.RephrasedQuestionsPrompt.system_prompt,
            human_content=prompts.RephrasedQuestionsPrompt.user_prompt.format(
                question=original_question,
                companies=", ".join([f'"{company}"' for company in companies])
            ),
            is_structured=True,
            response_format=prompts.RephrasedQuestionsPrompt.RephrasedQuestions
        )
        
        # Convert the answer_dict to the desired format
        questions_dict = {item["company_name"]: item["question"] for item in answer_dict["questions"]}
        
        return questions_dict


class AsyncOpenaiProcessor:
    
    def _get_unique_filepath(self, base_filepath):
        """Helper method to get unique filepath"""
        if not os.path.exists(base_filepath):
            return base_filepath
        
        base, ext = os.path.splitext(base_filepath)
        counter = 1
        while os.path.exists(f"{base}_{counter}{ext}"):
            counter += 1
        return f"{base}_{counter}{ext}"

    async def process_structured_ouputs_requests(
        self,
        model="gpt-4o-mini-2024-07-18",
        temperature=0.5,
        seed=None,
        system_content="You are a helpful assistant.",
        queries=None,
        response_format=None,
        requests_filepath='./temp_async_llm_requests.jsonl',
        save_filepath='./temp_async_llm_results.jsonl',
        preserve_requests=False,
        preserve_results=True,
        request_url="https://api.openai.com/v1/chat/completions",
        max_requests_per_minute=3_500,
        max_tokens_per_minute=3_500_000,
        token_encoding_name="o200k_base",
        max_attempts=5,
        logging_level=20,
        progress_callback=None
    ):
        from src.api_request_parallel_processor import process_api_requests_from_file

        # Create requests for jsonl
        jsonl_requests = []
        for idx, query in enumerate(queries):
            request = {
                "model": model,
                "temperature": temperature,
                "seed": seed,
                "messages": [
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": query},
                ],
                'response_format': type_to_response_format_param(response_format),
                'metadata': {'original_index': idx}
            }
            jsonl_requests.append(request)
            
        # Get unique filepaths if files already exist
        requests_filepath = self._get_unique_filepath(requests_filepath)
        save_filepath = self._get_unique_filepath(save_filepath)

        # Write requests to JSONL file
        with open(requests_filepath, "w") as f:
            for request in jsonl_requests:
                json_string = json.dumps(request)
                f.write(json_string + "\n")

        # Process API requests
        total_requests = len(jsonl_requests)

        async def monitor_progress():
            last_count = 0
            while True:
                try:
                    with open(save_filepath, 'r') as f:
                        current_count = sum(1 for _ in f)
                        if current_count > last_count:
                            if progress_callback:
                                for _ in range(current_count - last_count):
                                    progress_callback()
                            last_count = current_count
                        if current_count >= total_requests:
                            break
                except FileNotFoundError:
                    pass
                await asyncio.sleep(0.1)

        async def process_with_progress():
            await asyncio.gather(
                process_api_requests_from_file(
                    requests_filepath=requests_filepath,
                    save_filepath=save_filepath,
                    request_url=request_url,
                    api_key=os.getenv("OPENAI_API_KEY"),
                    max_requests_per_minute=max_requests_per_minute,
                    max_tokens_per_minute=max_tokens_per_minute,
                    token_encoding_name=token_encoding_name,
                    max_attempts=max_attempts,
                    logging_level=logging_level
                ),
                monitor_progress()
            )

        await process_with_progress()

        with open(save_filepath, "r") as f:
            validated_data_list = []
            results = []
            for line_number, line in enumerate(f, start=1):
                raw_line = line.strip()
                try:
                    result = json.loads(raw_line)
                except json.JSONDecodeError as e:
                    print(f"[ERROR] Line {line_number}: Failed to load JSON from line: {raw_line}")
                    continue

                # Check finish_reason in the API response
                finish_reason = result[1]['choices'][0].get('finish_reason', '')
                if finish_reason != "stop":
                    print(f"[WARNING] Line {line_number}: finish_reason is '{finish_reason}' (expected 'stop').")

                # Safely parse answer; if it fails, leave answer empty and report the error.
                try:
                    answer_content = result[1]['choices'][0]['message']['content']
                    answer_parsed = json.loads(answer_content)
                    answer = response_format(**answer_parsed).model_dump()
                except Exception as e:
                    print(f"[ERROR] Line {line_number}: Failed to parse answer JSON. Error: {e}.")
                    answer = ""

                results.append({
                    'index': result[2],
                    'question': result[0]['messages'],
                    'answer': answer
                })
            
            # Sort by original index and build final list
            validated_data_list = [
                {'question': r['question'], 'answer': r['answer']} 
                for r in sorted(results, key=lambda x: x['index']['original_index'])
            ]

        if not preserve_requests:
            os.remove(requests_filepath)

        if not preserve_results:
            os.remove(save_filepath)
        else:  # Fix requests order
            with open(save_filepath, "r") as f:
                results = [json.loads(line) for line in f]
            
            sorted_results = sorted(results, key=lambda x: x[2]['original_index'])
            
            with open(save_filepath, "w") as f:
                for result in sorted_results:
                    json_string = json.dumps(result)
                    f.write(json_string + "\n")
            
        return validated_data_list

# DashScope基础处理器，支持Qwen大模型对话
class BaseDashscopeProcessor:
    def __init__(self):
        load_dotenv()
        if dashscope is not None:
            dashscope.api_key = os.getenv("DASHSCOPE_API_KEY")
        self.default_model = 'qwen-turbo'

    @staticmethod
    def _raise_for_provider_error(response) -> None:
        if isinstance(response, dict):
            status_code = response.get("status_code")
            code = response.get("code")
            message = response.get("message")
            request_id = response.get("request_id")
            output = response.get("output")
        else:
            status_code = getattr(response, "status_code", None)
            code = getattr(response, "code", None)
            message = getattr(response, "message", None)
            request_id = getattr(response, "request_id", None)
            output = getattr(response, "output", None)

        if (isinstance(status_code, int) and status_code >= 400) or output is None:
            raise RuntimeError(
                "DashScope request failed: "
                f"status_code={status_code}, code={code or 'unknown'}, "
                f"message={message or 'no output returned'}, "
                f"request_id={request_id or 'unknown'}."
            )

    @staticmethod
    def _extract_content(response) -> str:
        if isinstance(response, dict):
            choices = response.get("output", {}).get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "")
        output = getattr(response, "output", None)
        choices = getattr(output, "choices", None)
        if choices:
            message = getattr(choices[0], "message", None)
            content = getattr(message, "content", None)
            if content is not None:
                return content
        raise RuntimeError("DashScope response does not contain message content.")

    @staticmethod
    def _extract_usage(response) -> Dict[str, Optional[int]]:
        usage = response.get("usage", {}) if isinstance(response, dict) else getattr(response, "usage", None)
        if usage is None:
            usage = {}
        if isinstance(usage, dict):
            input_tokens = usage.get("input_tokens")
            output_tokens = usage.get("output_tokens")
        else:
            input_tokens = getattr(usage, "input_tokens", None)
            output_tokens = getattr(usage, "output_tokens", None)
        return {"input_tokens": input_tokens, "output_tokens": output_tokens}

    def send_message(
        self,
        model="qwen-turbo",
        temperature=0.1,
        seed=None,  # 兼容参数，暂不使用
        system_content='You are a helpful assistant.',
        human_content='Hello!',
        is_structured=False,
        response_format=None,
        **kwargs
    ):
        """
        发送消息到DashScope Qwen大模型，支持 system_content + human_content 拼接为 messages。
        结构化请求会解析并通过 Pydantic Schema 校验；普通请求仍返回字符串。
        """
        if model is None:
            model = self.default_model
        if dashscope is None:
            raise ImportError("DashScope provider requires the 'dashscope' package.")
        if is_structured:
            if response_format is None:
                raise ValueError("response_format is required for structured DashScope output.")
            schema_json = json.dumps(
                response_format.model_json_schema(),
                ensure_ascii=False,
            )
            system_content = (
                f"{system_content}\n\n---\n\n"
                "Return only one JSON object that conforms to this JSON Schema:\n"
                f"{schema_json}"
            )
        # 拼接 messages
        messages = []
        if system_content:
            messages.append({"role": "system", "content": system_content})
        if human_content:
            messages.append({"role": "user", "content": human_content})
        #print('system_content=', system_content)
        #print('='*30)
        #print('human_content=', human_content)
        #print('='*30)
        #print('messages=', messages)
        #print('='*30)
        # 调用 dashscope Generation.call
        response = dashscope.Generation.call(
            model=model,
            messages=messages,
            temperature=temperature,
            result_format='message'
        )
        self._raise_for_provider_error(response)
        content = self._extract_content(response)
        usage = self._extract_usage(response)
        self.response_data = {"model": model, **usage}

        if is_structured:
            return parse_structured_response(content, response_format)
        return content
