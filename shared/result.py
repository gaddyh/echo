
def getAgentMessage(result):
    #print("result: ", result)
    messages = result["messages"]
    if isinstance(messages, list):
        last = messages[-1]
        # If last is an object, extract its dict or attribute
        if isinstance(last, dict) and "content" in last:
            return last["content"]
        elif hasattr(last, "content"):
            return last.content
    print(f"[DEBUG] Final message format unexpected: {repr(last)}")
    return None