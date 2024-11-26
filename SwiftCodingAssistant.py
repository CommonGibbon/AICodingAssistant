from openai import OpenAI
import os
import datetime
from pathlib import Path
import time
import pdb
import tiktoken
import ipywidgets as widgets
from IPython.display import display
from IPython.display import clear_output
from rich.console import Console
from rich.text import Text
from rich.syntax import Syntax
import re
from rich.markdown import Markdown
from tqdm.notebook import tqdm
from pydantic import BaseModel
import json

class ChangePlan(BaseModel):
    filesToModify: list[str]
    plan: str

class CodeObject():
    def __init__(self, code, isUpdated, target):
        self.code = code
        self.isUpdated = isUpdated
        self.target = target

class CodingAssistant():
    codeContents = {}
    codeSummaries = {}
    selectedCode = {}

    def __init__(self, projectPath, client):
        self.projectPath = projectPath
        self.lastReadTime = None
        self.client = client

        developerInstructions = """
            You are an expert SwiftUI iOS 18 programmer who helps add features to a codebase.
            You write SwiftUI code without using uikit. When asked to write code, you will instruct the user on where to put 
            the code. Your user does not know best practice for writing swift programs. When applicable you should instruct the user how to organize 
            their code. When responding, do repeat back to the user unmodified code. If you are editing a file, provide comment markers such as 
            'existing code' in place of existing, but unmodified code.",
            """
        architectInstructions = """
        You are an expert code planning assistant.  You will be provided with a summary of the contents of each file in a project and a request from the user.
            Your job is to:
            (1) decide which files should be modified as part of this update. Your response must be machine readable and this section should not contain any text outside of the file names.
            Since this must be machine readable, it is absolutely critical that you get the file names right. Double check that the files you name match those specified in the code 
            summaries. Don't forget to add the .swift file extension.
            (2) analyze the provided code base and the feature request, then generate a plan for implementing the feature.
                1. Overview of the feature and how it integrates with the existing code.
                2. Step-by-step breakdown of the changes or additions needed in the code base.
                3. Key considerations such as potential challenges, dependencies, or edge cases.
                4. Suggested best practices or optimizations for clean, maintainable code.
                It is critical that you do not write any code yourself! It is also critical tha you keep your plan succict and to the point. Do not cover unit testing or give advise on what 
                the developer should test after developing as part of your response.
            """

        self.developer = self.client.beta.assistants.create(
          name = "SwiftUI Developer",
          instructions = developerInstructions,
          tools = [],
          model = "gpt-4o-2024-08-06",
        )

        self.architect = self.client.beta.assistants.create(
            name = "SwiftUI Architect",
            instructions = architectInstructions,
            model = "gpt-4o-2024-08-06",
            response_format={
               'type': 'json_schema',
               'json_schema': 
                  {
                    "name": "ChangePlan", 
                    "schema": ChangePlan.model_json_schema()
                  }
             } 
        )

        self.newCodeBase = True 
        self.getLatestCode()  # Read in the contents of the project repo
        self.getCodeSummaries()  # Generate summaries of each file in the repo
        self.console = Console(width = 175)
        self.thread = self.client.beta.threads.create()

    def getCodeSummaries(self, forceUpdates = False):
        """
        This generates code summaries. By default it will only generate summaries for files which have not yet been summarized, but you can use
        forceUpdate to update summaries for all files
        """
        if forceUpdates:
            self._getCodeSummaries([])
        else:
            # Find keys that are in codeContents but not in codeSummaries
            missingInSummaries = self.codeContents.keys() - self.codeSummaries.keys()

            # If there are keys missing in codeSummaries, call updateCodeSummaries
            if missingInSummaries:
                self._getCodeSummaries(missingInSummaries)

        # Find keys that are in codeSummaries but not in codeContents
        extraInSummaries = self.codeSummaries.keys() - self.codeContents.keys()

        # If there are extra keys in codeSummaries, delete them (presumable the file was removed from the project)
        for key in extraInSummaries:
            del self.codeSummaries[key]

    def getLatestCode(self, extension = ".swift"):
        """
        Get all files in a self.projectPath with a specific extension that have been modified after a given timestamp.
        :param extension: The file extension to filter by (default is ".swift").
        """

        # Iterate over all files in the self.projectPath
        if type(self.projectPath) == list:
            for path in self.projectPath:
                self._getLatestCode(path, extension)
        else:
            self._getLatestCode(self.projectPath, extension)

        self.lastReadTime = time.time()
        
    def _getLatestCode(self, path, extension = ".swift"):
        """
        Get all files in a self.projectPath with a specific extension that have been modified after a given timestamp.
        :param extension: The file extension to filter by (default is ".swift").
        """
        target = os.path.basename(os.path.dirname(path)) # the target is the folder name in the path
        # Iterate over all files in the the supplied path
        for root, _, files in os.walk(path):
            for file in files:
                # Check if the file has the desired extension
                if file.endswith(extension):
                    filePath = os.path.join(root, file)

                    # Get the last modified time of the file
                    fileModifiedTime = datetime.datetime.fromtimestamp(os.path.getmtime(filePath)).timestamp()

                    # Check if the file was modified after the provided timestamp
                    if self.lastReadTime is None or fileModifiedTime > self.lastReadTime:
                        with open(filePath, "r") as f:
                            fileName = os.path.basename(filePath)
                            self.codeContents[fileName] = CodeObject(f"{fileName}:\n{f.read()}", True, target)

    def getTokenCount(self, message):
        # this seems useless for rate limit monitorying; I track that my token counts are a fraction of what they actually are for the purposes of blocking me due to rate limiting
        # then agian I think I'm misunderstanding how rate limiting works with the assistants API. 
        return len(tiktoken.encoding_for_model("gpt-4o").encode(message))

    def printFormattedText(self, textBlock):
        # Regular expression to find Swift code blocks
        codePattern = re.compile(r"```swift(.*?)```", re.DOTALL)

        # Split the text into parts: non-code text and Swift code blocks. 
        # Since we split on the code pattern, and WE ASSUME both (1) a code block will not start alone and 
        # (2) two code blocks wont follow back to back without normal text between, we can assume that odd indices will correspond to swift code
        parts = codePattern.split(textBlock)

        # Iterate over the parts and print them appropriately
        for i, part in enumerate(parts):
            if i % 2:
                #swift_code = swift_code_blocks[i].strip()
                syntax = Syntax(parts[i].strip(), "swift", theme = "xcode", line_numbers = False)
                self.console.print(syntax, no_wrap = False)
            else:
                # Print non-code text as regular text
                self.console.print(Markdown(part.strip()), no_wrap = False)

    def getErrorWaitTime(self, inputString, defaultValue = 15.0):
        # chatgpt outputs a suggested wait time before you should retry your request when you get a rate limit error. 
        # Use regex to find the seconds value
        match = re.search(r'in (\d+\.\d+)s', inputString)

        # If a match is found, convert it to a float, otherwise return the default value
        if match:
            return float(match.group(1))
        else:
            return defaultValue

    def _getCodeSummaries(self, fileSubset = []):
        # fileSubset: optionally only update the summaries for a subset of files

        instructions = """
        You are an expert swiftui programmer, when given the contents of a code file, you succinctly summarize its basic information, such as types of functions or classes it contains,
        and its basic function within the project. It is critical that you remain brief and keep your output to three sentences or less!
        """

        if not len(fileSubset):
            fileSubset = list(self.codeContents.keys())

        # Could use batching instead of this, but that's only necessary if I'm getting rate limited. 
        # Could parallelize this to speed it up. 
        # have simtheory read the page on rate limiting and update this function accordingly. 
        print("Generating file summaries...")
        for idx, file in enumerate(tqdm(fileSubset)):
            response = self.client.chat.completions.create(
                        model = "gpt-4o",
                        messages = [
                            {
                              "role": "system",
                              "content": [
                                    {
                                      "type": "text",
                                      "text": instructions
                                    }
                              ]
                            },
                            {
                              "role": "user",
                              "content": [
                                    {
                                      "type": "text",
                                      "text": f"Please summarize this file from the {self.codeContents[file].target} target:\n{self.codeContents[file].code}"
                                    }
                              ]
                            }
                        ]
                    )

            self.codeSummaries[file] = response.choices[0].message.content

    def ask(self, newQuestion, forceUpdateSummaries = False):
        self.newQuestion = newQuestion
        self.forceUpdateSummaries = forceUpdateSummaries
        # show the user file upload options. Once the user has made their selections, the request will be processed.
        return self._ask()
        #self.selectFileOptions()
   
    
    def _ask(self):
        self.getLatestCode()  # update to the latest code
        self.getCodeSummaries(self.forceUpdateSummaries)  # this won't do anything unless there are new files to summaries or you use forceUpdateSummaries

        #############################
        # Architect run
        messageBlocks = []
        codeSeen = {k for k in self.codeContents if not self.codeContents[k].isUpdated}  # this is the set of files the LLM has previously seen in full (and has not been updated since)
        if self.newCodeBase:
            # this is the first message, so we send special instructions
            messageBlocks.append("These are the file summaries for each file in the codebase you will be assisting with:")
        else:
            messageBlocks.append("I have updated the codebase. Here are the new file summaries:")

        codeToSummarize = self.codeSummaries.keys() - (codeSeen)  # exclude files we've just uploaded and those we've uploaded previously
        for file in codeToSummarize:
            messageBlocks.append(f"\n{self.codeSummaries[file]}")

        messageBlocks.append(self.newQuestion)
        message = self.client.beta.threads.messages.create(
          thread_id = self.thread.id,
          role = "user",
          content = "\n".join(messageBlocks)
        )

        # create the architect code plan (automatically appended to the thread)
        architectRun = self.client.beta.threads.runs.create_and_poll(
            thread_id = self.thread.id, assistant_id = self.architect.id
        )
        if architectRun.status == "failed":
            print("Error with architect run")
            return architectRun

        # Get the code plan response. We onlt need to know what files we're to modify, but we're going to log the plans as well, as this is an experimental feature.
        messages = list(self.client.beta.threads.messages.list(thread_id = self.thread.id, run_id = architectRun.id))
        if not len(messages):
            print(f"ERROR: {messages}")
            return architectRun
        plan = json.loads(messages[0].content[0].text.value)
        self.lastPlan = plan["plan"]
        filesToModify = set(plan["filesToModify"])
        if not filesToModify.issubset(self.codeContents.keys()):
            print(f"ERROR: architect did not return valid file names: {filesToModify}")
            return None
        
        #############################
        # Developer run
        # for the full code:
        filesToLoad = filesToModify - codeSeen
        messageBlocks = ["These are the full files you'll be modifying:"] if filesToLoad else [] # reset message blocks for the next message
        for file in filesToLoad: 
            messageBlocks.append(f"\nFrom {self.codeContents[file].target} target:\n{self.codeContents[file].code}")
        # submit the question and code summaries to the assistant
        messageBlocks.append("Please use this code and the code plan to attend to the user's question")
        message = self.client.beta.threads.messages.create(
            thread_id = self.thread.id,
            role = "user",
            content = "\n".join(messageBlocks)
        )

        # have the developer write the code according to the user's request and the architect's plan
        developerRun = self.client.beta.threads.runs.create_and_poll(
            thread_id = self.thread.id, assistant_id = self.developer.id
        )
        if developerRun.status == "failed":
            print("Error with developer run")
            return developerRun

        # get the message(s) from the last run
        messages = list(self.client.beta.threads.messages.list(thread_id = self.thread.id, run_id = developerRun.id))
        if not len(messages):
            print(f"ERROR: {messages}")
            return {"architectRun": architectRun, "developerRun": developerRun}
        messageContent = messages[0].content[0].text.value
        #self.printFormattedText(messageContent)
        print(messageContent)

        self.newCodeBase = False
        for file in self.selectedCode:
            self.codeContents[file].isUpdated = False  # track that the LLM has now seen this code

        return messageContent

    def onSubmitClicked(self):
        if not self.selectedCode:
            print("ERROR: you must select code to submit to the LLM.")
        else:
            clear_output()
            self.selectedCode = {cb.description for cb in checkboxes if cb.value}
            return self._ask()

    def selectFileOptions(self):
        # Create checkboxes for each file
        checkboxes = [widgets.Checkbox(value = False, description = f"{file}: {self.codeSummaries[file]}", layout = widgets.Layout(width = 'auto')) for file in self.codeSummaries.keys()]

        # Create a button to submit the selection
        submitButton = widgets.Button(description = "Submit Selection")

        # Display checkboxes and button
        display(*checkboxes, submitButton)

        # Attach the function to the button click event
        submitButton.on_click(self.onSubmitClicked)