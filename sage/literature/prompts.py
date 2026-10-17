# Derived from CoI-Agent (Li et al.), Apache-2.0.
# Source: https://github.com/DAMO-NLP-SG/CoI-Agent, commit ac94317ff2d1997f362747edc2c9e5f0fdc9c450.
# MODIFIED for SAGE, 2026-10-17: split by capability; strict output contracts,
# evidence-scope rules, concise rationale, mutable default removal.
# See ../../LICENSES/CoI-Agent-Apache-2.0.txt and ../../NOTICE.md.
"""Maintained SAGE prompts adapted from CoI-Agent; no upstream runtime imports."""
use_entities = True

def get_deep_reference_prompt(paper_content: str,topic) -> str:
    prompt = f"""
You are a scientific research expert, tasked with extracting and summarizing information from provided paper content relevant to the topic: {topic}. Your deliverables will include pertinent references, extracted entities, a detailed summary, and the experimental design.

The topic you are studying is: {topic}. (Ensure that the references are pertinent to this topic.)

Extraction Requirements:
Entities
1. Identify unique entities mentioned in the paper, such as model names, datasets, metrics, and specialized terminology.
2. Format the entities with a name followed by a brief description.
3. Ensure all entities are relevant to the specified topic ([topic]).


Summary Idea:
1. Background: Elaborate on the task's context and previous work, outlining the starting point of this paper.
2. Novelty: Describe the main innovations and contributions of this paper in comparison to prior work.
3. Contribution: Explain the primary methods used, detailing the theory and functions of each core component.
4. Detail Reason: Provide a thorough explanation of why the chosen methods are effective, including implementation details for further research.
5. Limitation: Discuss current shortcomings of the approach.

Experimental Content:
1. Experimental Process: Detail the entire experimental procedure, from dataset construction to specific steps, ensuring clarity and thoroughness.
2. Technical Details: Describe any specific technologies involved, providing detailed implementation processes.
3. Clarity of Plan: State your experimental plan concisely to facilitate understanding without unnecessary complexity.
4. Baseline: Elaborate on the baseline used, comparative methods, and experimental design, illustrating how these support and validate the conclusions drawn.
5. Verification: Explain how your experimental design assists in verifying the core idea and ensure it is detailed and feasible.

Relevance Criteria:
1. Method Relevance: References must directly correlate with the paper's methodology, indicating improvements or modifications.
2. Task Relevance: References should address the same task, even if methods differ, better have the same topic {topic}.
3. Baseline Relevance: References should serve as baselines for the methods discussed in the paper.
4. Output Format: Provide references without author names or publication years, formatted as titles only.
5. Specific paper titles will be placed between <References></References>. Based on the precise citation location and the corresponding ref_id in the paper, you need to infer the specific title of your output relevant references.


The paper content is as follows:
{paper_content}


Please provide the entities, summary idea, experimental design, and the three most relevant references (Sort by relevance, with priority given to new ones with the same level of relevance, do not reference the original paper.) based on the paper's content.
Note: Ensure the references are pertinent to the topic you are studying: {topic}. If there are no relevant references, output <references>[]</references>.

Now please output strictly in the following format:
<entities>{{A list of entities you extract}}</entities>
<idea>{{Background: ... \nNovelty: ...\nContribution:...\nMethods:...\nDetail reason:...\nLimitation:...\n }}</idea>
<experiment>{{Step1:... Step2:...}}</experiment>
<references>["{{Title1}}", "{{Title2}}",  ...]</references>
"""
    return prompt


def get_deep_judge_relevant_prompt(target_paper_title,target_paper_abstract,topic) -> str:
    prompt = f"""
You are an expert researcher tasked with evaluating whether a given paper is relevant to our research topic.

Below are the details of the paper you need to assess:
Title: {target_paper_title}
Abstract: {target_paper_abstract}

The topic is: {topic}

if the paper title and abstract are related to the topic, output <relevant>1</relevant>, otherwise output <relevant>0</relevant>. As long as you feel that this article has reference value for your question, you can use it to help you study the topic, it does not need to be completely consistent in topic.

Please output strictly in the following format(no extra content):
<think>{{a brief evidence-based rationale}}</think>
<relevant>{{0/1}}</relevant>
    """
    return prompt
