This setup submits a code repository to ChatGPT for analysis. One API assistant (architect) reviews code summaries and identifies files to modify, while the other (writer) processes only those files to provide text and code responses for tasks like optimization or feature addition. This two-assistant process is necessary due to rate-limit restrictions for most non-commercial api users.
Although this is written for swiftUI support, generalization to other languages and platforms should be easy to do.

Setup requirements: 
- environment variable for OpenAI API
- install necessary packages

Sample usage:
client = OpenAI()
assistant = CodingAssistant("/Users/willshannon/Documents/ios_projects/ChineseStories/ChineseStrories/", client)

request = """
Type your request here
"""

response = assistant.ask(request)

This will print out the LLM response. If there is something wrong with the response, you can debug it with the response dictionary object.