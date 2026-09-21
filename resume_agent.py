import asyncio
import os

from langchain_core.output_parsers import PydanticOutputParser
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from dotenv import load_dotenv
from typing import Annotated, Sequence, TypedDict
from langgraph.graph import END,START,StateGraph
from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage
from langgraph.graph.message import add_messages
from docx import Document
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import interrupt, Command
import httpx

load_dotenv()

def load_resume(path:str)->str:
    doc=Document(path)
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())

class JobInfo(BaseModel):
    title: str
    company:str
    location:str
    requirements:list[str]
    description:str
    url:str

class JobListResult(BaseModel):
    jobs: list[JobInfo]

class ProfilerOutput(BaseModel):
    job_profile: str = Field(description="岗位整体画像（核心技能、职责、经验要求、加分项），必须是包含 Markdown 格式的文本字符串，绝对不能是 JSON 对象或字典!")
    skill_analysis:str = Field(description="技能匹配度分析（匹配项、缺失项、可迁移技能、整体评价），必须是包含 Markdown 格式的文本字符串，绝对不能是 JSON 对象或字典！")
    resume_suggestions: str = Field(description="简历优化建议列表，必须是包含 Markdown 格式的文本字符串，绝对不能是 JSON 数组或列表！")

class ResumeAgentState(TypedDict):
    #用户信息
    job_intent:str            #意向岗位
    resume: str               #用户原始简历

    #researcher输出
    job_list: list[JobInfo]   #岗位列表

    #profiler输出
    job_profile:str           #岗位画像
    skill_analysis:str        #技能分析
    resume_suggestions:str    #简历优化意见

    #interview输出
    interview_qa:str

    #控制流：
    opinion:str               #是否修改简历
    suggestion:str            #用户对简历的修改建议
    messages: Annotated[Sequence[BaseMessage],add_messages]


llm=ChatOpenAI(
    model="deepseek-chat",
    base_url="https://api.deepseek.com/v1",
    temperature=0.0,
    api_key=os.getenv("OPENAI_API_KEY"),
    http_client=httpx.Client(trust_env=False),
    http_async_client=httpx.AsyncClient(trust_env=False),
)


parser = PydanticOutputParser(pydantic_object=JobListResult)
def researcher_agent(state:ResumeAgentState):
    researcher_prompt = f"""
   你是一个岗位研究员。
    根据用户的求职意向 {state["job_intent"]}，搜索招聘网站。
    要求：
    1. 只返回真实的招聘信息，不要臆造岗位。
    2. 返回岗位列表，字段名必须严格使用以下 schema 中的名称，不要改名。
    3. 必须返回 20 个岗位，如果搜索结果不足 20 个，请扩大搜索范围（如放宽地区、增加相关岗位关键词、搜索更多招聘网站）直到凑满 20 个。
    
    {parser.get_format_instructions()}
    """
    structured_llm=llm.with_structured_output(JobListResult,method="json_mode")
    result=structured_llm.invoke([SystemMessage(content=researcher_prompt)])
    job_list=[job.model_dump() for job in result.jobs]

    return {"job_list": job_list}


def profiler_agent(state:ResumeAgentState):
    profiler_prompt =f"""
    你是一个岗位画像师。
    输入：一批同类岗位：{state["job_list"]} + 简历：{state["resume"]}
    任务：
    1. 聚合出这类岗位的整体画像（核心技能、职责、经验要求、加分项)
    2. 分析用户技能与画像的匹配度，提取和强调用户信息和岗位相匹配的内容
    3. 给出面向这类岗位的简历优化建议，如果用户信息没有很匹配的可以根据岗位画像去添加简历内容
    【输出格式严格要求】：
- JSON 必须包含且仅包含三个 Key：`job_profile`, `skill_analysis`, `resume_suggestions`。
- 每个 Key 对应的 Value **必须是单一的文本/Markdown格式字符串（String）**，严禁使用 JSON 对象({{...}})、数组([...])或字典格式嵌套！
- 示例正确格式：
  {{
    "job_profile": "### 核心技能\\n- Python\\n- RAG...\\n### 职责... ",
    "skill_analysis": "### 匹配分析\\n用户具备Python能力，匹配度较高...",
    "resume_suggestions": "1. 建议在专业技能中增加LLM相关描述..."
  }}
    """
    structured_llm=llm.with_structured_output(ProfilerOutput, method="function_calling")
    response=structured_llm.invoke([SystemMessage(content=profiler_prompt)])
    print(f"""
        job_list：{state["job_list"]}
        岗位画像：{response.job_profile}\n\n,
        技能分析：{response.skill_analysis}\n\n,
        简历建议：{response.resume_suggestions}\n

    """)
    return{"job_profile":response.job_profile,
           "skill_analysis":response.skill_analysis,
           "resume_suggestions":response.resume_suggestions,
           }

def resume_agent(state:ResumeAgentState):
    resume_prompt =f"""
    你是一个简历制作专家。
    任务：
    1.根据岗位画像{state["job_profile"]}、技能分析{state["skill_analysis"]}、简历修改建议{state["resume_suggestions"]}、用户意见{state["suggestion"]}
    去修改简历{state["resume"]}，写出一份符合岗位要求，简历通过率高的简历。
    只输出修改后的完整简历正文，不要输出任何解释、前言或markdown代码块标记
    """
    response=llm.invoke([SystemMessage(content=resume_prompt)])
    modify_resume=response.content
    return{"resume":modify_resume}

def human_review(state:ResumeAgentState):
    #payload，相当于print，仅做展示
    feedback=interrupt({
        "type":"resume_review",
        "question":"您对当前简历满意吗(Y/N)？不满意的话请直接写修改意见。",
        "resume":state["resume"],
    })
    print(f"""human_review恢复，feedback={feedback!r}""")
    opinion=feedback.get("opinion")
    suggestion=feedback.get("suggestion")

    print(f"""opinion={opinion!r}""")
    return {"opinion":opinion,
            "suggestion":suggestion,
            }

def router_satisfy(state:ResumeAgentState)->str:
    print(f"""收到opinion={state["opinion"]!r}""")
    fb=state["opinion"].strip().lower()
    print(f"""判断fb？opinion：{fb!r}""")
    print("判断结果：",fb=="y")
    if fb =="y":
         return "satisfied"
    else:
        return "unsatisfied"


def interview_agent(state:ResumeAgentState):
    print("进入interview环节")
    interview_prompt =f"""
    你是一个面试专家。
    任务：
    分析岗位信息{state["job_profile"]}和用户简历{state["resume"]}，整理出用户在面试该岗位时高频面试问题和优秀的面试回答
    """
    response=llm.invoke([SystemMessage(content=interview_prompt)])
    return {"interview_qa":response.content}

def build_agent_workflow()->StateGraph:
    workflow = StateGraph(ResumeAgentState)
    workflow.add_node("researcher",researcher_agent)
    workflow.add_node("profiler",profiler_agent)
    workflow.add_node("resume",resume_agent)
    workflow.add_node("human_review",human_review)
    workflow.add_node("interview",interview_agent)

    workflow.add_edge(START,"researcher")
    workflow.add_edge("researcher","profiler")
    workflow.add_edge("profiler", "resume")
    workflow.add_edge("resume","human_review")
    workflow.add_conditional_edges("human_review",router_satisfy,{"satisfied":"interview","unsatisfied":"resume"})
    workflow.add_edge("interview",END)

    return workflow

memory=MemorySaver()
bot=build_agent_workflow().compile(checkpointer=memory)

#用户交互主循环
async def run_resume_builder():
    intend_job=input("请输入你的目标岗位：")
    thread_id="1"
    config={"configurable":{"thread_id":thread_id}}

    resume = load_resume("resume.docx")


    initial_state={
        "messages":[HumanMessage(content=intend_job)],
        "job_intent":intend_job,
        "resume":resume,
        "job_list":[],
        "job_search_errors": [],
        'job_profile': ""  ,
        'skill_analysis': ""  ,
        'resume_suggestions': "" ,
        "opinion": "",
        "suggestion": "",
        "interview_qa": ""
    }

    result=await bot.ainvoke(initial_state,config)

    #图每跑到human_review就会返回一个__interrupt__，循环处理
    while "__interrupt__" in result:
        payload=result["__interrupt__"][0].value
        print(f"简历已完成：\n{payload['resume']}\n\n{payload['question']}")

        #用户反馈：
        user_input=input("您对当前简历满意吗？（Y/N）").strip()

        #将用户满意反馈追加到历史信息，resume=是langchain的固定用法，Command 的 resume 参数，语义是"恢复执行时给中断点的输入值"，它不是 state 更新。不要混淆
        if user_input.lower()=="y":
            result=await bot.ainvoke(Command(resume={"opinion":"y","suggestion":""}),config)
        else:
            revision_ideas=input("请输入您的修改意见（例如：增加项目细节、突出品质）：").strip()
            result=await bot.ainvoke(Command(resume={"opinion":"n","suggestion":revision_ideas}),config)
    print(f"\n优化完成，为您生成最终简历:\n,{result['resume']}")
    print(f"\n\n以下是关于这个岗位的面试高频问答：:\n,{result['interview_qa']}")
    # print(result["messages"][-1].content)

if __name__ == "__main__":
    asyncio.run(run_resume_builder())










