import streamlit as st
import os, asyncio, json
import nest_asyncio
from openai import OpenAI
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from dotenv import load_dotenv

# 1. Patch for Streamlit's event loop management
nest_asyncio.apply()
load_dotenv()

# --- Page Configuration ---
st.set_page_config(page_title="Zomato AI Agent", page_icon="🍔", layout="centered")

# 2. API Key Gatekeeper (Multi-user safe)
if "openai_api_key" not in st.session_state:
    st.title("🍔 Welcome to Zomato AI Agent")
    st.info("Enter your OpenAI API key to start.")
    
    user_key = st.text_input("OpenAI API Key", type="password", placeholder="sk-...")
    if st.button("Unlock Chat"):
        if user_key.startswith("sk-"):
            st.session_state.openai_api_key = user_key
            st.rerun()
        else:
            st.error("Invalid API key format.")
    st.stop()

# --- Initialize Session State ---
if "messages" not in st.session_state:
    st.session_state.messages = [
        {"role": "system", "content": "You are a helpful Zomato assistant. Use tools to find food and place orders."}
    ]

# --- Core Agent Logic ---
async def get_zomato_response(user_input):
    client = OpenAI(api_key=st.session_state.openai_api_key)
    
    # 🚨 CLOUD FIX: Use 'sh' to tell the Linux server to search for 'npx'
    server_params = StdioServerParameters(
        command="sh", 
        args=["-c", "npx -y mcp-remote https://mcp-server.zomato.com/mcp"],
        env=os.environ.copy()
    )

    try:
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                
                tools_resp = await session.list_tools()
                available_tools = [
                    {"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.inputSchema}}
                    for t in tools_resp.tools
                ]

                # Update local message history
                st.session_state.messages.append({"role": "user", "content": user_input})
                
                response = client.chat.completions.create(
                    model="gpt-4o",
                    messages=st.session_state.messages,
                    tools=available_tools,
                )

                response_message = response.choices[0].message
                
                if response_message.tool_calls:
                    # Save OpenAI object as dict for history serializability
                    st.session_state.messages.append(response_message.model_dump())
                    
                    for tool_call in response_message.tool_calls:
                        tool_name = tool_call.function.name
                        tool_args = json.loads(tool_call.function.arguments)
                        
                        with st.status(f"🛠️ Zomato: {tool_name}...", expanded=False):
                            result = await session.call_tool(tool_name, tool_args)
                            
                            st.session_state.messages.append({
                                "role": "tool",
                                "tool_call_id": tool_call.id,
                                "name": tool_name,
                                "content": str(result.content),
                            })

                    final_response = client.chat.completions.create(
                        model="gpt-4o",
                        messages=st.session_state.messages,
                    )
                    return final_response.choices[0].message.content
                
                return response_message.content

    except Exception as e:
        return f"❌ **Error**: {str(e)}"

# --- UI Loop ---
st.title("🍔 Zomato AI Agent")

for msg in st.session_state.messages:
    if msg["role"] == "system": continue
    if msg.get("content") and msg["role"] in ["user", "assistant"]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

if prompt := st.chat_input("I want to order pizza..."):
    with st.chat_message("user"):
        st.markdown(prompt)
    
    with st.chat_message("assistant"):
        with st.spinner("Talking to Zomato..."):
            response = asyncio.run(get_zomato_response(prompt))
            st.markdown(response)
            st.session_state.messages.append({"role": "assistant", "content": response})

# Sidebar
with st.sidebar:
    if st.button("Reset Chat"):
        st.session_state.messages = [{"role": "system", "content": "You are a helpful Zomato assistant."}]
        st.rerun()