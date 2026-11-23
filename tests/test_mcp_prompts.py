import asyncio

from gotoquill.mcp_server import build_server


def test_try_gotoquill_lists_without_arguments_and_gets_user_message():
    async def run():
        server = build_server()
        prompts = await server.list_prompts()
        prompt = next(prompt for prompt in prompts if prompt.name == "try_gotoquill")
        assert prompt.title == "Try Gotoquill"
        assert not prompt.arguments
        for arguments in (None, {}):
            result = await server.get_prompt("try_gotoquill", arguments)
            assert len(result.messages) == 1
            message = result.messages[0]
            assert message.role == "user"
            assert message.content.type == "text"
            text = message.content.text
            assert text.startswith(
                "Create a short sample NDA between my company and Dana Cohen, then let me sign it."
            )
            assert "request_signature" in text
            assert "pdf_path, pdf_url, or pdf_base64" in text
            assert "examples/sample_contract.pdf" in text
            assert "If no PDF is available, ask me to attach one." in text
            assert "review the PDF and consent in the signing UI" in text
            assert "open_signing_card" not in text
            assert "\u2014" not in text

    asyncio.run(run())
