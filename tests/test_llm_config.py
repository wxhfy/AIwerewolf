from backend.llm import create_client


def test_create_client_infers_deepseek_from_model() -> None:
    client = create_client(provider=None, model="deepseek-v4-flash")
    assert client.base_url == "https://api.deepseek.com"
    assert client.model == "deepseek-v4-flash"
