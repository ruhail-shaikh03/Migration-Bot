# AFTER
from openai import OpenAI          # ← sync client, no Async prefix
import streamlit as st

def get_deepseek_client() -> OpenAI:
    return OpenAI(
        api_key=st.secrets["app"]["deepseek_api_key"],
        base_url="https://api.deepseek.com/v1",
    )