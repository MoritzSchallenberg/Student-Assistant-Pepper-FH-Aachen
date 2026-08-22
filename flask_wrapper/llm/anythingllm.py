import requests
#from . import API_BASE_URL, API_TOKEN

class anything_llm_helper:
    def __init__(self, url, api_token):
        self.base_url = url
        self.headers = {
            'accept': 'application/json',
            'Authorization': f'Bearer {api_token}'
        }

    def get_workspaces(self):
        url = f"{self.base_url}/workspaces"
        response = requests.get(url, headers=self.headers)

        if response.status_code == 200:
            return response.json()
        else:
            response.raise_for_status()
    
    def send_chat_message(self, slug, message, mode="chat"):
        """
        Sends a chat message to a specific workspace.

        :param slug: Workspace identifier
        :param message: Message to send
        :param mode: Mode of the message (default is "chat")
        :return: Response from the API
        """
        url = f"{self.base_url}/workspace/{slug}/chat"
        payload = {
            "message": message,
            "mode": mode
        }
        headers = self.headers.copy()
        headers['Content-Type'] = 'application/json'

        response = requests.post(url, headers=headers, json=payload)

        if response.status_code == 200:
            return response.json()
        else:
            response.raise_for_status()

    def stream_chat_message(self, slug, message, mode="chat"):
        """
        Streams chat messages from the API.

        :param slug: Workspace identifier
        :param message: Message to send
        :param mode: Mode of the message (default is "chat")
        :return: Generator yielding streamed chunks of text
        """
        url = f"{self.base_url}/workspace/{slug}/stream-chat"
        payload = {
            "message": message,
            "mode": mode
        }
        headers = self.headers.copy()
        headers['Content-Type'] = 'application/json'

        response = requests.post(url, headers=headers, json=payload, stream=True)

        if response.status_code == 200:
            # Stream chunks of data
            for chunk in response.iter_content(chunk_size=None):
                if chunk:
                    yield chunk.decode('utf-8')
        else:
            response.raise_for_status()
