# Derived from CoI-Agent (Li et al.), Apache-2.0.
# Source: https://github.com/DAMO-NLP-SG/CoI-Agent, commit ac94317ff2d1997f362747edc2c9e5f0fdc9c450.
# MODIFIED for SAGE, 2026-10-17: split by capability; strict output contracts,
# evidence-scope rules, concise rationale, mutable default removal.
# See ../../LICENSES/CoI-Agent-Apache-2.0.txt and ../../NOTICE.md.
"""Maintained SAGE prompts adapted from CoI-Agent; no upstream runtime imports."""
use_entities = True

def get_deep_generate_experiment_prompt(idea,experiments,entities) -> str:
    prompt = f"""
You are a scientific expert tasked with designing rigorous, feasible, and impactful experiments based on specified scientific questions and the methodologies derived from the idea I provide, along with relevant past research. Your goal is to assist researchers in systematically testing hypotheses and validating innovative discoveries that could significantly advance their fields.

Past Related Research Experiments: {experiments}

Here are the entities you need to know: {entities}.

Here is the idea you need to design an experiment for: {idea}.

Please propose a detailed experimental plan addressing the following points:
1. Experimental Design: Develop rigorous experiments to ensure the reliability and validity of your results. Provide a comprehensive explanation of the baseline used, comparative methods, ablation study design, and criteria for data analysis and result evaluation. Clarify how these components collectively reinforce and validate the conclusions of your research. Structure your experimental design in a clear, logical, and step-by-step manner, ensuring each step is well-defined and easy to understand.
2. Implementation of Technologies/Methods: If your experimental design involves specific technologies or methodologies, describe the implementation process in detail, including key technical aspects. For any critical concepts utilized, provide thorough explanations. For instance, if you propose a modular approach, detail its construction, components, and functionality.
3. Feasibility Assessment: Ensure your experimental plan is realistic, considering technological availability, timelines, resources, and personnel. Identify potential challenges and propose strategies for addressing them.
4. References to Previous Studies: When citing related literature, include titles and pertinent details of the original papers. Strive to use as many references as necessary to support your experimental design.
5. Visual Aids: If useful, provide pseudocode or a flowchart to illustrate the implementation process. For example, you can use pseudocode to detail the core algorithm or the model architecture, or employ a flowchart to map out the experimental procedure and data flow.
6. Clarity of Language: Use straightforward language to describe your methods, assuming the reader may have limited knowledge of the subject matter. Avoid complex jargon and utilize accessible terminology. If professional terms are necessary, please provide clear and detailed explanations.


Please output strictly in the following format:
<experiment>{{your experimental plan}}</experiment>

For example:
<experiment> Step1: ... \n Step2: ..., ..., ... </experiment>
"""
    return prompt


def get_deep_refine_experiment_prompt(experiment,suggestions,paper_infos=None,entities = None) -> str:
    infos = f"""
The literature infos you maybe need to refer to are as follows: {paper_infos}
""" if paper_infos else ""

    prompt = f"""
You are a research expert tasked with refining and improving an experimental plan based on the feedback received.

{infos}

The experimental plan you proposed is as follows:
{experiment}

Please propose a detailed experimental plan addressing the following points:
1. Experimental Design: Develop rigorous experiments to ensure the reliability and validity of your results. Provide a comprehensive explanation of the baseline used, comparative methods, ablation study design, and criteria for data analysis and result evaluation. Clarify how these components collectively reinforce and validate the conclusions of your research. Structure your experimental design in a clear, logical, and step-by-step manner, ensuring each step is well-defined and easy to understand.
2. Implementation of Technologies/Methods: If your experimental design involves specific technologies or methodologies, describe the implementation process in detail, including key technical aspects. For any critical concepts utilized, provide thorough explanations. For instance, if you propose a modular approach, detail its construction, components, and functionality.
3. Feasibility Assessment: Ensure your experimental plan is realistic, considering technological availability, timelines, resources, and personnel. Identify potential challenges and propose strategies for addressing them.
4. References to Previous Studies: When citing related literature, include titles and pertinent details of the original papers. Strive to use as many references as necessary to support your experimental design.
5. Visual Aids: If useful, provide pseudocode or a flowchart to illustrate the implementation process. For example, you can use pseudocode to detail the core algorithm or the model architecture, or employ a flowchart to map out the experimental procedure and data flow.
6. Clarity of Language: Use straightforward language to describe your methods, assuming the reader may have limited knowledge of the subject matter. Avoid complex jargon and utilize accessible terminology. If professional terms are necessary, please provide clear and detailed explanations.

You have received the following suggestions for improvement:
{suggestions}

Please refine your experimental plan based on the feedback provided. Ensure your refined plan is feasible, clearly defined, and addresses the feedback you received.

Please output strictly in the following format:
<experiment>{{your refined experimental plan}}</experiment>
"""
    return prompt


def get_deep_refine_experiment_search_query_prompt(experiment,suggestions):
    prompt = f"""
You are a research expert tasked with refining and improving an experimental plan based on the feedback received.

The experimental plan you proposed is as follows:
{experiment}

You have received the following suggestions for improvement:
{suggestions}

Please decide whether you need to search for relevant papers to obtain relevant knowledge to improve your experiment.

If you need to search for relevant papers, please provide a  search query(only a conciese phrase) for literature search, else provide "".
For example: if suggestions say that the dynamic query additional information and update knowledge graph described in the experiment is not clearly described, so you need to output <query>dynamic knowledge graph update</query>(only a conciese phrase) .

Please output strictly in the following format:
<query>{{the search query}}</query>, or <query></query> if no search is needed.

For example:
<query>Reducing reliance on large-scale annotated data and closed-source models for planning in QA tasks</query>
"""
    return prompt


def get_deep_paper_info_prompt_for_refine_experiment(paper,experiment,suggestions) -> str:
    prompt = f"""
You are a scientific research expert.
Your task is to research the relevant literature to refine your experiment.

The literature you need to study is:
{paper}

The experiment designed for the idea is:
{experiment}

You have received the following suggestions for improvement:
{suggestions}

Please extract useful information from the paper that can help you improve your experiment.For example, if the paper describes a method or dataset or matric that can be used in your experiment, you should extract this method.

Please output strictly in the following format:
<info>{{The information you extracted from the paper}}</info>
"""
    return prompt
