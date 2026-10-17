# Derived from CoI-Agent (Li et al.), Apache-2.0.
# Source: https://github.com/DAMO-NLP-SG/CoI-Agent, commit ac94317ff2d1997f362747edc2c9e5f0fdc9c450.
# MODIFIED for SAGE, 2026-10-17: split by capability; strict output contracts,
# evidence-scope rules, concise rationale, mutable default removal.
# See ../../LICENSES/CoI-Agent-Apache-2.0.txt and ../../NOTICE.md.
"""Maintained SAGE prompts adapted from CoI-Agent; no upstream runtime imports."""
use_entities = True

def get_deep_check_idea_novel_search_query_prompt(idea,topic: str) -> str:
    prompt = f"""
You are a scientific research expert.
Your task is to check whether the target idea is similar to existing research.

The target idea you need to check is as follows:{idea}

The topic you are studying is: {topic}

Please provide multiple search queries to find relevant papers that can help you determine whether the idea is novel(no more than 3 queries).

Output strictly in the following format:
<queries>["query1", "query2", "query3"]</queries>

For example:
<queries>["Reducing reliance on large-scale annotated data and closed-source models for planning in QA tasks","Automatic agent learning for QA","QA task planning with minimal human intervention"]</queries>
"""
    return prompt


def get_deep_check_idea_novel_prompt(idea,papers):
    papers_content = ""
    for i,paper in enumerate(papers):
        papers_content += f"Paper {i}: Title:{paper.title}\n Abstract:{paper.abstract}\n"
    prompt = f"""
You are a scientific research expert tasked with evaluating the similarity between a specified idea and existing research. Your objective is to determine if the target idea closely resembles any findings in the provided papers.

The target idea you need to check is as follows:
{idea}

The relevant papers you need to refer to are as follows:
{papers_content}

Here are your guidlines:
1. Comparison Process: Begin by thoroughly comparing each paper's ideas with the target idea. Consider the methodologies, conclusions, and underlying concepts in each paper in your analysis.
2. Similarity Assessment: If the target idea shares fundamental similarities with any existing research to the extent that they can be considered identical, flag potentially overlapping prior work; this is not a plagiarism determination.
3. Output: Your output should provide a clear thought process, the similarity assessment, a summary of the target idea, and the ID of the most relevant similar paper.

Please output strictly in the following format:
<think>{{a brief evidence-based rationale}}</think>
<similar>{{0/1}}</similar>
<summary>{{the summary of the target idea}}</summary>
<similar_paper_id>{{the id of the similar paper}}</similar_paper_id>

For example:
<think> There are my think steps:... </think>
<similar>0</similar>
<summary> It proposes ... </summary>
<similar_paper_id>0</similar_paper_id>
"""
    return prompt


def get_judge_idea_all_prompt(idea0,idea1,topic):
    prompt = f"""
You are a judge in a competition. You have to decide which idea is better.

The idea0 is: {idea0}

The idea1 is: {idea1}

The topic is: {topic}

Which idea do you think is better? Please write a short paragraph to explain your choice.

Here are your evaluation criteria:
1. Novelty: Are the problems or approaches new? Is this a novel combination of familiar techniques? Is it clear how this work differs from previous contributions? Is related work adequately referenced?
2. Significance: Are the idea important? Are other people (practitioners or researchers) likely to use these ideas or build on them? Does the idea address a difficult problem in a better way than previous research? Does it provide a unique theoretical or pragmatic approach?
3. Feasibility: Can the idea be realized with existing technology or methods? Are there any technical difficulties or bottlenecks? Is the idea clear and logical? Is there any obvious error or unreasonable part in the idea, and can the experiment be designed normally according to this idea.
4. Clarity: Is the paper clearly written? Is it well-organized? Does it adequately inform the reader?
5. Effectiveness: How likely the proposed idea is going to work well (e.g., better than existing baselines).

Note:
Avoid any position biases and ensure that the order in which the responses were presented does not influence your decision. DO NOT allow the LENGTH of the responses to influence your evaluation, choose the one that is straight-to-the-point instead of unnecessarily verbose. Be as objective as possible. (very important!!!)

If you think idea0 is better than idea1, you should output 0. If you think idea1 is better than idea0, you should output 1. If you think idea0 and idea1 are equally good, you should output 2.

Your output should be strictly in following format:
Brief rationale:
...

Your choice:
<novelty>{{ Your choice for novelty }}</novelty>
<relevance>{{ Your choice for relevance to the topic }}</relevance>
<significance>{{ Your choice for significance }}</significance>
<feasibility>{{ Your choice for feasibility }}</feasibility>
<clarity>{{ Your choice for clarity }}</clarity>
<effectiveness>{{ Your choice for effectiveness }}</effectiveness>
    """
    return prompt


def get_judge_experiment_all_prompt(idea0,experiment0,idea1,experiment1):
    prompt = f"""
You are a judge in a competition. You have to decide which experiment is better.
The idea of experiment0 is: {idea0}
The experiment0 is: {experiment0}

The idea of experiment1 is: {idea1}
The experiment1 is: {experiment1}

Which experiment do you think is better? Please write a short paragraph to explain your choice.

Here are your evaluation criteria:
1. Feasibility: Can the experiment be realized with existing technology or methods? Are there any technical difficulties or bottlenecks? Is the experimental plan detailed and feasible? Are the experimental steps clear and logical? Is there any obvious error or unreasonable part in the experiment. Consider the rationality of its steps and the possibility that the idea can be successfully implemented.
2. Quality: Is there a clear rationale for each step of the experimental design? Are the baseline and evaluation metrics chosen appropriately? Has the design taken into account the potential advantages and limitations of the methods used? Can this experimental design effectively support the claims made in the idea.
3. Clarity: Is the experimental plan clearly written? Dose it provide enough information for the expert reader to understand the experiment? Is it well organized? Does it adequately inform the reader?

Note: Avoid any position biases and ensure that the order in which the responses were presented does not influence your decision. DO NOT allow the LENGTH of the responses to influence your evaluation, choose the one that is straight-to-the-point instead of unnecessarily verbose. Be as objective as possible. (very important!!!)

If you think experiment0 is better than experiment1, you should output 0. If you think experiment1 is better than experiment0, you should output 1. If you think experiment0 and experiment1 are equally good, you should output 2.

Your output should be strictly in following format:
Brief rationale:
...

Your choice:
<feasibility>{{Your choice for feasibility}}</feasibility>
<quality>{{Your choice for quality}}</quality>
<clarity>{{Your choice for clarity}}</clarity>
    """
    return prompt


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
