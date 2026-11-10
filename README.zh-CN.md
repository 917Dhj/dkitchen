<p align="center">
  <img src="https://raw.githubusercontent.com/917Dhj/dkitchen/main/docs/assets/dkitchen.png" width="240" alt="两个像素风机器人厨师：大的按响服务铃，小的端着锅应声而来">
</p>

<h1 align="center">dkitchen</h1>

<p align="center">
  <a href="README.md">English</a> | <b>简体中文</b>
</p>

<p align="center">
  <b>你决定做什么菜，agent 们把厨房转起来。</b> 🧑‍🍳
</p>

<p align="center">
  <a href="https://pypi.org/project/dkitchen/"><img src="https://img.shields.io/pypi/v/dkitchen" alt="PyPI"></a>
  <a href="https://pypi.org/project/dkitchen/"><img src="https://img.shields.io/pypi/pyversions/dkitchen" alt="Python"></a>
  <a href="https://github.com/917Dhj/dkitchen/actions/workflows/tests.yml"><img src="https://github.com/917Dhj/dkitchen/actions/workflows/tests.yml/badge.svg" alt="Tests"></a>
  <a href="https://github.com/917Dhj/dkitchen/blob/main/LICENSE"><img src="https://img.shields.io/github/license/917Dhj/dkitchen" alt="License"></a>
  <a href="https://x.com/dahuoji09"><img src="https://img.shields.io/badge/follow-%40dahuoji09-000000?logo=x" alt="X: @dahuoji09"></a>
</p>

dkitchen 是我每天用来跑科研仓库的多 agent 工作流。它给一组 Claude Code 和 Codex 会话分好岗位，约定它们怎么通过 GitHub issue 交接工作、什么时候必须停下来问你，并配齐把这一切串起来的工具。只有你能做的决定留给你：研究什么、试什么、花多少。

## 🍽️ 为什么是厨房

AI agent 让执行变得很便宜，瓶颈于是落到了你身上。

只开一个 agent，每一步都得你盯着。开好几个，你就成了传话筒：在会话之间来回复制上下文，查任务跑完没有，记住哪个会话在做哪件事，一整天都在批小事。上一个实验早就跑完了，没人发现，GPU 就这么空着。到了晚上，什么都碰过了，却什么都没想。

米其林餐厅的后厨解决的是同一个问题。主厨定菜单、尝味道；其他人各守一个岗位，每道菜都是一张单子，菜做好了就敲一下铃。主厨不切洋葱，也从不对厨房里的事失去掌控。

dkitchen 就这样组织你的 agent。你是主厨。

## 🧑‍🍳 厨房里的岗位

<p align="center">
  <img src="https://raw.githubusercontent.com/917Dhj/dkitchen/main/docs/assets/kitchen-zh.webp" width="100%" alt="像素风的厨房：你和总设计定下方案，总编排按铃让 Codex 执行者用上空闲 GPU，执行者直接找总设计提问，总核查审 PR、总编排合并；然后你去睡觉，厨房按夜班令照常运转，早上把一件需要你决定的事带给你">
</p>

| 岗位 | 在后厨相当于 | 做什么 | 由谁担任 |
| --- | --- | --- | --- |
| 👑 **你** | 主厨 | 定方向，批设计和预算，判断结果对论文意味着什么。 | 你 |
| 🤖 **总编排** | 出菜口的副主厨 | 排票、排 GPU 和并发；合并 PR、关票，向你汇报事实。 | Claude Code · Claude Opus 5.5 |
| 🤔 **总设计** | 研发菜谱的厨师 | 写票，设计方法和所有模型会看到的文字，解读结果。 | Claude Code · Claude Opus 5.5 |
| 🔍 **总核查** | 试菜的人 | 对照代码和数据抽查跑完的运行和产物，并审 PR。只报告查到了什么，不做决定。 | Claude Code · Claude Sonnet 5.5 |
| 🔪 **执行者** | 各灶台的厨师 | 一张票一个新会话，各自一个工作树。实现、运行，并在票里汇报。 | Codex · GPT-6.1 Sol |

每个岗位都有成文的规则：自己负责什么、交给谁、什么时候必须停下。哪个岗位都不归的事，agent 会来问你。

## 🎫 一张票怎么走完整个厨房

1. **你和总设计商量好要做什么。** 总设计把它写成一个 GitHub issue：目标、具体步骤、一张说明什么时候算做完的门槛表，以及预计的花费。
2. **总编排派发这张票**，开一个新的执行者会话，挑空闲的 GPU。
3. **执行者开工前核对票面的前提**，对照代码和数据；有一条不成立，就把票交回总设计。
4. **执行者干活，并在票里汇报。** 每条留言开头都是同样的四行：状态、在等谁、关键数字、下一步。长任务用 `ding launch` 启动，任务退出时 `ding` 唤醒执行者，让它看输出、接着干。
5. **结果直接交给总设计解读。** 总核查按提交逐次审 PR；审查和 CI 都通过后，总编排合并。
6. **你读一份简短的汇报**，做下一个决定。

每个决定、申请和结果都留在票里。任何一个会话，或者一周后的你，都能从 GitHub 上把来龙去脉接上。

## ✋ 留给你的事

规则写明了哪些决定属于主厨：

- 研究方向、数据集怎么用、论文里怎么说；
- 装了运行预算模块时：每张票的预算（批一次）、换模型或换端点、启动服务。

在这些事上，agent 只提建议，然后等你。批准只认你自己的原话，总编排和总设计都不能替你批。

其余的事厨房自己处理，判断标准只有一条：**换谁来做结果都一样的事，agent 直接做；有几种合理做法、选哪种会影响结果、花费或方向的，停下来等你。**

正因为这样，你才能走开。你上课、睡觉或者读论文的时候，每个岗位都有自己的 watch，活到了它手上就唤醒它：执行者做完一个阶段、卡住或者长时间没动静，你留了言，PR 可以审了。走开之前，`/goodnight` 收齐夜里可能用到的批准；总编排按这些批准推进，`/goodmorning` 把剩下要你拍板的事带给你。

## ⚖️ 一个统一的资源池

一个科研仓库手里的资源，比任何单个 agent 看得到的都多：几台服务器上的 GPU、共享的模型服务、CPU 时间、API 预算、token，还有一天里的时间。在 dkitchen 里，总编排用你手上最强的模型，把它们当成一个池子统一调度。

- 🖥️ **算力。** 在空闲的 GPU 之间排票；加并发之前先看共享模型服务的负载。
- 💰 **钱。** 每张要跑模型的票都带一份批好的估算，包括调用数、费用和 GPU 卡·时。运行对照它汇报，预计花费超过估算 1.5 倍时提醒一次；只有失控的花费才会让运行停下。
- 🪙 **Token。** 一张票一个会话，每个会话的上下文都很小；核对事实交给更便宜的模型。
- ⏱️ **时间。** 任务一退出就唤醒负责它的会话，不用等谁想起来去看。

## 🧰 厨具

### 🛎️ `ding`，出菜铃

`ding` 在 agent 会话之间传话，并在长任务结束时唤醒对应的会话。

```bash
ding new --cwd . --issue 42 --name '消融实验' --message-file brief.md   # 为 #42 新建 Codex 会话，打印它的 UUID
ding board                                            # 这个仓库里谁在做什么
ding send '#42' --from orchestrator --message-file note.md
ding launch train -- python train.py                  # 在 tmux 里跑，退出时唤醒我
```

指定会话可以用 UUID、会话名，或者 GitHub issue，比如 `'#42'`；`ding` 会找到认领这张票的会话。在 Linux 上，`ding board` 还会列出没用 `ding` 启动的长时间进程，方便你发现那些跑完了也没人会被唤醒的任务。

`ding` 通过 Codex App Server 和 Codex 会话通信。完整用法见 [docs/ding.md](https://github.com/917Dhj/dkitchen/blob/main/docs/ding.md)（英文）。

### 📋 厨房的日常流程

各岗位每天要做的固定动作也做成了 `ding` 命令，每次都按同样稳妥的方式执行：

- `ding relay` 给票的执行者发消息，确认送达后才在票里留记录。
- `ding review` 将审查结论绑定到当前 PR HEAD。配置 `[merge] review_check` 后，`ding merge`、`ding watch` 和 `ding waits` 共用 PR 就绪判断；所有合并都要求目标为默认分支。详见 [review 与 merge 文档](docs/ding.md)。
- `ding watch` 在每个岗位后台等着，票需要它时唤醒它。
- `ding waits` 列出超时未回应的等待，包括上一批 watch 之后还没处理的。
- `ding log` 记下你不在时总编排做了什么。
- `ding night` 在这份日志上开启、查看和关闭有时限的夜间指令。在总编排会话里运行 `/goodnight` 和 `/goodmorning`，收集指令并汇报使用情况。
- `ding check-refs` 核对总核查引用的每个文件、行号和摘要。
- `ding check` 在每个 PR 上跑仓库检查，`ding map` 列出库里的模块，让改动落到已有的模块上。

### 📜 厨房规矩

每个岗位遵守的规则在 [kitchen/](https://github.com/917Dhj/dkitchen/blob/main/kitchen/README.md)（英文），厨房的每一块一个目录：团队（谁负责什么、票、审 PR、什么时候停下来问你，以及运行预算和模型提示词两个可选模块）、仓库的代码规范和检查、运行器，以及你不在时的夜班。规则管的是以后，不是清理过去；改检查要在提交里用 `Guard-change:` 写明理由。

### 🧩 Skills

插件会装上十个 skill。搭建类 skill 各搭厨房的一块，以后可以再跑一次原地更新：

| Skill | 做什么 |
| --- | --- |
| `/setup-dkitchen` | 入口：检查前提条件，定好语言和你需要哪几块，再依次走下面的搭建 skill |
| `build-team` | 岗位、票、审 PR 和 watch；仓库里有几类不同的工作时，可以建议加设计线 |
| `build-repo` | 代码放哪、模块原地改，以及 CI 里的 `ding check` 关卡（Python 仓库） |
| `build-runner` | 一个可续跑的运行器，用于逐条处理的工作，比如评测和批量推理（Python 仓库） |
| `build-night` | 夜间指令和总编排日志，你不在时工作也能往前走 |

日常类 skill 在厨房运转时使用：

| Skill | 什么时候用 |
| --- | --- |
| `write-ticket` | 每次有岗位写票；模型会自己调用 |
| `/shift-change` | 某个岗位换成新会话时交接 |
| `/improve-kitchen` | 每两周左右一次：把反复出错的地方做成检查、工具或规则，并删掉被它们取代的文字 |
| `/goodnight`、`/goodmorning` | 你走开之前和回来之后 |

## 🚀 开始使用

### 环境要求

- Linux 或其他 POSIX 系统，装有 `tmux`
- Python 3.10 及以上
- 一个 GitHub 仓库和 `gh` 命令行
- Claude Code，以及在同一用户下运行着 App Server 的 Codex

### 1. 安装 `ding`

```bash
pipx install dkitchen
```

### 2. 把 skill 加进 Claude Code

```bash
claude plugin marketplace add 917Dhj/dkitchen
claude plugin install dkitchen@dkitchen
```

### 3. 搭你自己的厨房

在你的仓库里打开 Claude Code，运行：

```text
/setup-dkitchen
```

这个 skill 会先读你的仓库，了解你在做什么、已经有什么：agent 说明文件、测试、GPU、模型调用、长任务。它检查前提条件，定好语言，再问你需要哪几块：团队、代码规范、运行器、夜班。然后依次走每一块的搭建 skill；每个 skill 一次问一个问题，把打算写入的每一条规则、每个脚本和每项 GitHub 改动先拿给你看，你同意后才写。之后想改设置，随时再运行一次。

从 0.5 升级？先读 [CHANGELOG](https://github.com/917Dhj/dkitchen/blob/main/CHANGELOG.md)（英文）里的 *Upgrading*。

## ❓ 常见问题

**让 agent 无人值守地跑，安全吗？**
凡是会改变方向、结果或花费的事，它们都会停下；批准只认你在票里的原话。每个动作都是 GitHub 上的一条留言或一个 PR，第二天早上喝咖啡的时候就能把昨晚的事查一遍。

**适合我的仓库吗？**
这些规则是为计算类科研写的，其中大部分也适用于任何有长任务的仓库。安装 skill 会按你的仓库改写这些规则。团队和夜班不挑编程语言；代码检查和运行器只支持 Python 仓库。

**必须同时用 Claude Code 和 Codex 吗？**
目前是的，这是我每天在用的组合。

**我的仓库里已经有很多不合规的老代码，装了会不会 CI 一片红？**
不会。布局检查只看 PR 新加的文件，老代码永远不会让它失败。Ruff 和导入规则看整个仓库，所以对每一项已有违规的检查，`build-repo` 要么在这次安装里顺手修掉（违规少、改法机械时），要么先关掉这项检查，另开一张清理票，清理完再打开。没有基线，也没有例外清单：这两样只会越积越多。

**小项目用这么多流程，会不会太重？**
总编排、总设计和总核查总是一起装；代码规范、运行器和夜班都是可选的。规则只装每个厨房都需要的部分，其余的由 `/improve-kitchen` 根据你的厨房里真正出过的问题慢慢长出来。

## 💡 关于

*d* 是我的记号。dkitchen 是我管自己厨房的方式，写下来，好让你也能开起自己的厨房。它诞生在我的科研仓库里：这个仓库在最初的四周里，用这套工作流处理了 171 个 issue，合并了 111 个 PR。

米其林后厨这个比喻来自 Lauren Tan，网名 [Poteto](https://github.com/poteto)。这套工作流的很多做法都受到了 Poteto 管理 agent 方式的启发。用 GitHub issue 管票的做法，最初改自 [Matt Pocock 的 skills](https://github.com/mattpocock/skills) 里的 issue tracker 配置。谢谢两位。🙏

## 许可证

[MIT](LICENSE)
