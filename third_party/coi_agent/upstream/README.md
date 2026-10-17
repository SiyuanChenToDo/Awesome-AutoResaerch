<p align="center">
    <img src="assets/logo.jpg" width="16%" height="25%">
    <img src="assets/title.png" width="55%" height="55%">
</p>

<h3 align="center">
Chain-of-Ideas Agent: Revolutionizing Research Via Novel Idea Development with LLM Agents
</h3>

<font size=3><div align='center' > [[📖 arXiv Paper](https://arxiv.org/pdf/2410.13185)] [[📊 Online Demo](https://huggingface.co/spaces/DAMO-NLP-SG/CoI_Agent)] </div></font>


<p align="center">
<a href="https://opensource.org/license/apache-2-0"><img src="https://img.shields.io/badge/Code%20License-Apache_2.0-green.svg"></a>
<a href="https://github.com/DAMO-NLP-SG"><img src="https://img.shields.io/badge/Institution-DAMO-red"></a>
<a><img src="https://img.shields.io/badge/PRs-Welcome-red"></a>
</p>


## 🔥 News
* **[2024.10.12]**  The first version of CoI Agent!


## 🛠️ Requirements and Installation
**Step 1**:
```bash
git clone https://github.com/DAMO-NLP-SG/CoI-Agent.git
cd CoI-Agent
pip install -r requirements.txt
```

**Step 2**:
Install [SciPDF Parser](https://github.com/titipata/scipdf_parser) for PDF parsing.
```bash
git clone https://github.com/titipata/scipdf_parser.git
pip install git+https://github.com/titipata/scipdf_parser
python -m spacy download en_core_web_sm
```

**Step 3**:
Install java for grobid
```bash
wget  https://download.oracle.com/java/GA/jdk11/9/GPL/openjdk-11.0.2_linux-x64_bin.tar.gz
tar -zxvf openjdk-11.0.2_linux-x64_bin.tar.gz
export JAVA_HOME=Your_path/jdk-11.0.2
```

**Step 4**:
set config.yaml to use the LLM APIs.
```yaml
# Sementic scholor api, it should be filled
SEMENTIC_SEARCH_API_KEY: ""

is_azure : True # if false, it is openai

# set it if you set is_azure to True
AZURE_OPENAI_ENDPOINT : ""
AZURE_OPENAI_KEY : ""
AZURE_OPENAI_API_VERSION : ""

# set it if you set is_azure to False
OPENAI_API_KEY: ""
OPENAI_BASE_URL: ""

# if not set it will be set to the same as main llm
EMBEDDING_API_KEY: ""
EMBEDDING_API_ENDPOINT: ""
EMBEDDING_MODEL: ""

MAIN_LLM_MODEL: "" # "gpt-4o" or ...

CHEAP_LLM_MODEL: "" # "gpt-4o" or ...
```

## 🚀 Quick Start
**Step 1**: Run grobid

If you can successfully start grobid in [SciPDF Parser](https://github.com/titipata/scipdf_parser.git), run the following commands:
```bash
cd scipdf_parser
bash serve_grobid.sh
```

(Optional) Or, you can refer to the following process to install grobid if the previous commands fail:
```bash
git clone https://github.com/kermitt2/grobid.git
cd grobid
./gradlew clean install
./gradlew run
```

**Step 2**: Generate idea
```python
python main.py --topic {your research topic}
```

## 📖 Evaluation Data
All evaluation data as well CoI generated results can be found in `dataset` fold.

## :black_nib: Citation

If you find our work helpful for your research, please consider starring the repo and citing our work.   

```bibtex
@article{li2024chain,
  title={Chain of Ideas: Revolutionizing Research in Novel Idea Development with LLM Agents},
  author={Li, Long and Xu, Weiwen and Guo, Jiayan and Zhao, Ruochen and Li, Xinxuan and Yuan,
            Yuqian and Zhang, Boqiang and Jiang, Yuming and Xin, Yifei and Dang, Ronghao and 
            Rong, Yu and Zhao, Deli and Feng, Tian and Bing, Lidong},
  journal={arXiv preprint arXiv:2410.13185},
  year={2024},
  url={https://arxiv.org/abs/2410.13185}
}
```
