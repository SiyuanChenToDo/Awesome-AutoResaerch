# Derived from CoI-Agent (Li et al.), Apache-2.0.
# Source: https://github.com/DAMO-NLP-SG/CoI-Agent, commit ac94317ff2d1997f362747edc2c9e5f0fdc9c450.
# MODIFIED for SAGE, 2026-10-17: split by capability; strict output contracts,
# evidence-scope rules, concise rationale, mutable default removal.
# See ../../LICENSES/CoI-Agent-Apache-2.0.txt and ../../NOTICE.md.
"""Maintained SAGE prompts adapted from CoI-Agent; no upstream runtime imports."""
use_entities = True

def get_deep_trend_idea_chains_prompt(idea_chains,entities,topic) -> str:
    entities = f"""
Here are the entities you need to know: {entities}
""" if use_entities else ""
    prompt = f"""
You are a scientific research expert tasked with summarizing the historical progression of research related to our current topic, based on the literature we have reviewed.

{entities}

The topic you are studying is: {topic}

The literature from early to late: {idea_chains}

Your objective is to outline the historical evolution of the research in light of current trends. Please follow these requirements:
Analysis of Published Viewpoints: Examine the progression of ideas across the identified papers. Detail how each paper transitions to the next—for instance, how Paper 0 leads to Paper 1, and so forth. Focus on understanding how Paper 1 builds upon the concepts in Paper 0. Elaborate on specific advancements made, including proposed modules, their designs, and the rationale behind their effectiveness in addressing previous challenges. Apply this analytical approach to each paper in the sequence.


Please present your findings in the following format:
<trend> {{The research trend you summarized based on the past work}} </trend>

Example:
<trend>from Paper 0 to Paper 1: ... \nfrom Paper 1 to Paper 2: ... \n </trend>
"""
    return prompt


def get_deep_generate_future_direciton_prompt(idea_chains,trend,topic,entities) -> str:
    entities = f"""
Here are the entities you need to know: {entities}
""" if use_entities else ""
    prompt = f"""
You are a scientific research expert tasked with proposing future research directions based on the literature we have reviewed.

{entities}

The topic you are studying is: {topic}

The literature you have studied is as follows:
{idea_chains}

The following section delineates the progressive relationships among the previously summarized research papers:
<the begin of previous trend>{trend}</the end of previous trend>

Based on previous research, analyze how human experts think and transition from previous methods to subsequent approaches. Focus on their reasoning logic and the sources of their thought processes. Learn to emulate their reasoning patterns to further develop and guide your own research direction in a natural and coherent manner.

You are encouraged to adopt the following four modes of thinking:
1. Reflection: Reflect on scenarios where a specific method encounters significant challenges. Consider potential solutions that could effectively address these issues, make the solutions sounds reasonable, novel and amazing.
2. Analogy:  Identify a specific problem you are currently facing. Analyze whether similar issues exist in other fields and how those areas have addressed these problems. Consider if their solutions can be adapted and applied to resolve your current challenge.
3. Deep Dive: Some methods may present specific approaches to addressing a particular problem. Consider whether there are aspects that could be modified to enhance their rationale and effectiveness.
4. Imitate: Analyze the research methods used in previous studies and reflect on how they have progressively advanced the research. Identify common strategies or particularly useful approaches, and use these insights to guide the direction of your next research step. (Most recommended)

Note:Each article's limitations are specific to that particular piece and should not be applied to others. Carefully consider the task at hand and analyze the potential issues you might encounter if you proceed with your original approach, reflecting on the challenges previously faced. Then, think critically about how to address these issues effectively.

You are encouraged to apply human reasoning strategies to identify future research directions based on prior studies. Aim for in-depth analysis rather than mere integration of existing ideas. Please avoid introducing unfamiliar information, ensuring that the trends you present are both authentic and reasonable. Before proposing any trends, take a moment to reflect on the principles underlying the methods you're employing and assess their relevance to your research area.

The future research direction should be related to the topic: {topic}.
Please output strictly in the following format:
<human>{{The human reasoning way you analyzed based on the previous research}}</human>
<future>{{the future research direction}}</future>
"""
    return prompt


def get_deep_generate_idea_prompt(idea_chains,trend,topic,entities,future = None,bad_case = None) -> str:
    bad_case_content = ""
    if bad_case:
        bad_case_content = "Previous candidates overlapped retrieved work. Address the specific overlap without claiming proven novelty:\n"
        for i, previous in enumerate(bad_case):
            bad_case_content += f"<example>{i}. Previous idea:{previous['idea']}\nAssessment:{previous['summary']}\nSimilar paper ID:{previous['similar_paper_id']}</example>\n"

    trend = f"""
The following section delineates the progressive relationships among the previously summarized research papers:
<the begin of previous trend>{trend}</the end of previous trend>
    """ if trend else ""

    future = f"""
The following section outlines the potential future research directions based on the literature you have studied:
<the begin of future>{future}</the end of future>
    """ if future else ""


    entities = f"""
Here are the entities you need to know: {entities}
""" if use_entities else ""
    prompt = f"""
You are a scientific expert tasked with formulating a novel and innovative research idea based on your comprehensive literature review. Your objective is to propose a feasible approach that could significantly advance the field.

{bad_case_content}

{entities}

The topic you are studying is: {topic}

The literature you have studied is as follows:
{idea_chains}

Task: Based on the current literature, propose a research idea that incorporates the following components:

Your idea is composed of the following components:
Motivation:
1. Provide a background for your idea, summarizing relevant past work.
2. Identify shortcomings in previous research and highlight the specific problems that remain unsolved and that you aim to address.

Novelty:
1. Distinguish your proposed method from existing methods (preferably by naming specific approaches).
2. Detail the improvements your method brings compared to previous work.
3. Clearly outline at least three contributions your idea offers to the field, including the problems it resolves and the benefits it delivers.

Method:
1. Present a detailed description of your idea, focusing on the core method, the specific problem it solves, and enhancements over earlier research (citing relevant literature with titles).
2. Explain the step-by-step methodology, including the functions of each module and the rationale for why this approach effectively addresses previous challenges.

Please adhere to the following guidelines:
1. Your research idea should be innovative, feasible, and contribute meaningfully to the field.Please carefully examine the idea you have proposed, avoid immediate perception, and try to be different from the previous methods as much as possible.
2. Ensure your proposal is solid, clearly defined, and practical to implement. Logic should underpin your reasoning.
3. Write in clear, concise language aimed at an audience with limited background knowledge in the subject. Avoid complex technical jargon, but when professional terms are necessary, provide thorough explanations.
4. Refrain from introducing concepts from uncertain fields to prevent proposing ideas that may be incorrect or impractical.
5. When referencing other research, please include the titles of the cited papers.
6. Please avoid introducing unfamiliar information, ensuring that the trends you present are both authentic and reasonable. Before proposing any trends, take a moment to reflect on the principles underlying the methods you're employing and assess their relevance to your research area.
7. Each article's limitations are specific to that particular piece and should not be applied to others. Carefully consider the task at hand and analyze the potential issues you might encounter if you proceed with your original approach, reflecting on the challenges previously faced. Then, think critically about how to address these issues effectively.

{trend}

{future}

Please output strictly in the following format:
<motivation>{{the motivation of your idea}}</motivation>
<novelty> {{the novelty of your idea}} </novelty>
<method> {{the method of your idea}} </method>
    """
    return prompt


def get_deep_final_idea_prompt(idea_chains,trend,idea,topic):
    idea = f"""
Here is your thinking steps:
{idea}
    """ if idea else ""
    if idea and trend:
        trend = f"""The relationship between each paper are as follows: {trend}"""
    elif trend:
        trend = f"""
The following section outlines the progress relationships between the previously summarized research papers:
<the begin of summarize>{trend}</the end of summarize>
        """
    else:
        trend = ""

    prompt = f"""
    You are an scientific expert with the primary objective of proposing a research idea based on the literature you have studied. Your goal is to propose a novel, feasible, and innovative research idea that can advance the field.

    The topic you are studying is: {topic}

Here are the literature you have studied:
{idea_chains}

Task: Based on the current literature, propose a research idea that incorporates the following components:

Please adhere to the following guidelines:
1. Your research idea should be innovative, feasible, and contribute meaningfully to the field. Please carefully examine the idea you have proposed, avoid immediate perception, and try to be different from the previous methods as much as possible
2. Ensure your proposal is solid, clearly defined, and practical to implement. Logic should underpin your reasoning.
3. Write in clear language aimed at an audience with limited background knowledge in the subject. Avoid complex technical jargon, but when professional terms are necessary, provide thorough explanations.
4. Refrain from introducing concepts from uncertain fields to prevent proposing ideas that may be incorrect or impractical.
When referencing other research, please include the titles of the cited papers.


{trend}

{idea}

The idea should be related to the topic: {topic}.

The final idea should contains the title, clearly explain the origins, motivation, novelty, difference of previous works and challenges of your idea, detailing how you overcame these hurdles.
Please output strictly in the following format:
<final_idea> {{the final idea}} </final_idea>
"""
    return prompt
