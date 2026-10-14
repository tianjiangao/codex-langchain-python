"""User-run local login example; not executed by offline CI."""

from langchain_codex_sdk import ChatCodexSDK

if __name__ == "__main__":
    with ChatCodexSDK(model="gpt-6.1-sol") as llm:
        result = llm.invoke("Hello from LangChain. Reply briefly.")
        print(result.content)
        print(result.usage_metadata)
