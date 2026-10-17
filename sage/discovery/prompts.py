# Derived from CoI-Agent (Li et al.), Apache-2.0.
# Source: https://github.com/DAMO-NLP-SG/CoI-Agent, commit ac94317ff2d1997f362747edc2c9e5f0fdc9c450.
# MODIFIED for SAGE, 2026-10-17: split by capability; strict output contracts,
# evidence-scope rules, concise rationale, mutable default removal.
# See ../../LICENSES/CoI-Agent-Apache-2.0.txt and ../../NOTICE.md.
"""Maintained SAGE prompts adapted from CoI-Agent; no upstream runtime imports."""
use_entities = True

def get_deep_search_query_prompt(topic = None,query = None) -> str:
    if topic and query:
        prompt = f"""
    You are a master of literature searcher, tasked with finding relevant research literatures based on a specific topic and idea.

    Currently, we would like to study the following topic: {topic}.
    And we have the following idea: {query}.

    Please provide the literature search queries you would use to search for papers related to the topic and idea.
        """
    elif topic:
        prompt = f"""
    You are a master of literature searcher, tasked with finding relevant research literatures based on a specific topic.

    Currently, we would like to study the following topic: {topic}.

    Please provide the literature search queries you would use to search for papers related to the topic.
    """
    elif query:
        prompt = f"""
    You are a master of literature searcher, tasked with finding relevant research literatures based on a specific idea.

    Currently, we would like to search for papers related to the following idea: {query}.

    Please provide the literature search querie syou would use to search for papers related to the paper idea.
    """
    output_format = """
    Each query should be a string and should be enclosed in double quotes.It is best to output one query representing the whole and other queries representing other different aspects of the whole.(no more than 5 queries)

    Output strictly in the following format:
    <queries>["query1", "query2", ...]</queries>

    For example:
    <queries>["Reducing reliance on large-scale annotated data and closed-source models for planning in QA tasks","Automatic agent learning for QA","QA task planning with minimal human intervention", "Few-shot learning for QA"]</queries>
"""
    return prompt + output_format


def get_deep_rewrite_query_prompt(failed_query,topic):
    prompt = f"""
You are a master of search engine query writing. We want to utilize the literature search engine to find relevant paper.

The queries that have been used so far are as follows: {failed_query}. Unfortunately, no satisfactory answers were found. Please rewrite a query to help us locate the literature we need (do not repeat the failed query).

The topic you are studying is: {topic}.
Please provide a new search query to find the relevant papers.

Try to make your query more concise and general so that it can be used to search for a wide range of papers.
If you failed more than 5 times, you can use a short query(no more than 5 words) to search for the paper.
Please output strictly in the following format:
<query>{{new query}}</query>

For example:
<query>Reducing reliance on large-scale annotated data and closed-source models for planning in QA tasks</query>
"""
    return prompt
