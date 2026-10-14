import asyncio

from langchain_codex_sdk import ChatCodexSDK


async def main():
    with ChatCodexSDK(model="gpt-6.1-sol") as llm:
        response = await llm.ainvoke("Return a short greeting.")
        print(response.content)


if __name__ == "__main__":
    asyncio.run(main())
