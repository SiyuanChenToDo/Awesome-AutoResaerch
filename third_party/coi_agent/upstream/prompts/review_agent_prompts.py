def get_review_search_related_paper_prompt(idea,topic):
    prompt = f"""
You are a paper reviewer with expertise in the field. 

The paper presents the idea: {idea}. Your task is to conduct a thorough literature review in the relevant field to assess the feasibility and originality of this idea, and to determine whether it has already been explored by others.

Please provide the literature search queries(no more than 3 queries) you would use to search for papers related to the paper idea. 
Each query should be a string and should be enclosed in double quotes.

Your output should be strictly in the following format:
<queries> ["query1", "query2", ...] </queries>

For example:
<queries>["Reducing reliance on large-scale annotated data and closed-source models for planning in QA tasks","Automatic agent learning for QA","QA task planning with minimal human intervention"]</queries>
"""
    return prompt

def get_review_suggestions_from_papers_prompt(idea,topic,paper):
    prompt = f"""
You are a manuscript review expert.
Here are some relevant literature knowledge you have: {paper}.

Currently you are assessing a paper on the topic: {topic}. 
The idea presented in the paper is: {idea}. 

Please analyze the feasibility and novelty of the paper's idea and provide suggestions for improvement, if any. (If there are no suggestions, please do not include any output.)(Please include the title of the paper you are referencing in the suggestion section)
You should also pay attention to whether the idea is related to the topic we are studying({topic}), and analyze whether it can help us solve topic-related problems.

There are some suggestions for you to consider:
1. Point out any confusion you had while reading the idea and suggest changes.
2. Based on relevant knowledge, think about the feasibility of the idea, whether the design of each step is reasonable, whether the statement is clear, and put forward your relevant suggestions.
3. Think about how the method can be improved to increase its novelty and feasibility, while trying not to increase the complexity of the method.

Your output should be strictly in the following format:
<suggestions> {{your suggestions to modify the idea}} </suggestions>

if you have no suggestions, please provide:
<suggestions></suggestions>
"""
    
    return prompt



def get_review_experiment_design_suggestions_prompt(idea, experiment,entities):
    prompt = f"""
You are an expert in paper review. Your task is to analyze whether a given experiment can effectively verify a specific idea, as well as assess the detail and feasibility of the experiment.

Here are the relevant entities to consider: {entities}.

The idea presented is: {idea}.

The corresponding experiment designed for this idea is: {experiment}.

Please conduct your analysis based on the following criteria:
1. Can the experiment validate the idea? If not, identify the issues and suggest improvements to enhance its verification capability and feasibility.
2. Are there specific experimental procedures that are confusing or poorly designed? Discuss any methods that may not be feasible, uncertainties in constructing the dataset, or a lack of explanation regarding the implementation of certain methods.
3. Evaluate the clarity, detail, reasonableness, and feasibility of the experimental design.
4. Provide suggestions for improving the experiment based on the shortcomings identified in your analysis.
5. Focus solely on the experiment design; please refrain from altering the original idea.
6. Ensure that your suggestions are constructive, concise, and specific.

Please strictly follow the following format for output:
<suggestion>{{Suggestions for improving the experiment}}</suggestion>
"""
    return prompt
