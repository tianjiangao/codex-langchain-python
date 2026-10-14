from pydantic import BaseModel

from langchain_codex_sdk import ChatCodexSDK


class Answer(BaseModel):
    result: int
    note: str | None = None


if __name__ == "__main__":
    with ChatCodexSDK(model="gpt-6.1-sol") as llm:
        answer = llm.with_structured_output(Answer).invoke("Calculate 7 + 5. Set note to null.")
        print(answer.model_dump())
