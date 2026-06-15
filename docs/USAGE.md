# 使用指南：逐层 UMR 解析器 + 人工纠错

这是一套把英文句子**一层层剥开**成 [UMR](https://github.com/umr4nlp/umr-guidelines)
语义图的工具。它的核心理念是：人 parse 句子不是一步到位，而是一连串小判断——

1. 这是一件事，还是好几件事拼起来的？（discourse 层）
2. 主事件是哪个动词？周围挂着哪些短语？（predicate 层）
3. 每个短语跟事件是什么关系？（relation 层）
4. 每个短语内部是什么结构？（entity 层）……是从句就回到第 1 步。

每个判断是一个 **skill**，一个 **harness** 负责递归、依次调用这些 skill。
你还能**人工指出哪标错了**，纠正会沉淀成 heuristics，下次解析立刻生效——两种引擎都遵守。

---

## 0. 环境

- Python 3.9+，**零依赖**即可跑（`--engine mock`）。CI 在 3.9 / 3.11 / 3.13 上跑测试。
- 装了 spaCy 会让启发式标注更准（可选）：
  `pip install spacy && python -m spacy download en_core_web_sm`
- 想用模型判断（`--engine claude`），需要 PATH 上有 `claude` CLI。

---

## 1. 解析一个句子

```bash
# 默认 mock 引擎：离线、确定性的启发式
python harness.py "Edmund Pope tasted freedom today."

# 加 --trace 看"剥洋葱"的每一步（每行 = 一次 skill 调用）
python harness.py "Edmund Pope tasted freedom today." --trace

# 批量
python harness.py --file examples/sample_sentences.txt

# 用模型判断（同一套 skill，改由 claude 回答）
python harness.py "He denied any wrongdoing." --engine claude
```

输出是标准 Penman 记法：

```
(t / taste-01
    :ARG0 (p / person
        :name (n / name :op1 "Edmund" :op2 "Pope")
        :wiki "-")
    :ARG1 (f / freedom)
    :temporal (t2 / today)
    :aspect Performance
    :modstr FullAff)
```

`--trace` 会额外打出每一层的判断，方便你定位哪里标错了：

```
[umr-predicate] "Edmund Pope tasted freedom today."
    -> head taste-01; 3 phrase(s) bracketed; aspect=Performance
  [umr-role] "Edmund Pope"  -> taste-01 --:ARG0--> ...
  [umr-role] "today"        -> taste-01 --:temporal--> time word
```

---

## 2. 纠错：三种用法

发现哪标错了，把它记下来。纠正按**内容做键**（不绑定具体句子），所以一条纠正会
泛化到今后所有同类情形。三种加法，从最省事到最灵活：

### 2a. `review`——交互式逐条过一遍（推荐）

这是最自然的方式：跑一次解析，工具带你**逐个决策**走，你对每个判断说"对/改/跳过/退出"。

```bash
python correct.py review "She sent the parcel to him."
```

它会先打印当前 parse，然后逐条问你。每条提示后输入：

| 按键 | 含义 |
|------|------|
| 直接回车 | 保留这个判断 |
| `c` | 纠正它（接着会问你新值 + 可选备注） |
| `s` | 跳过剩下所有，直接结束 |
| `q` | 退出 |

一次真实会话长这样（`>` 后是你的输入）：

```
current parse:
(s / send-01
    :ARG0 (p / person ...)
    :ARG1 (p2 / parcel)
    :goal (p3 / person ...)        ← 这里标错了，应该是 :recipient
    :aspect Performance :modstr FullAff)

8 decisions to review. [Enter]=keep  c=correct  s=skip rest  q=quit

[1/8] umr-predicate:  head concept of "..." = send-01
    >                         ← 回车，保留
...
[7/8] umr-role:  send-01 --:goal--> "him"
    > c                       ← 要改
    new relation (current :goal, e.g. :recipient): :recipient
    note (optional): animate receiver
    ✓ correction recorded.
[8/8] umr-entity:  "him" parsed as person
    > s                       ← 后面都对，跳过

1 correction(s) recorded.
re-parse to see the effect? [Y/n]: y

updated parse:
(s / send-01
    ...
    :recipient (p3 / person ...)   ← 已修正
    ...)
```

不同层会问不同的东西：

- **umr-role**（边的关系）：输入新关系，如 `:recipient`、`:instrument`（会校验合法性）。
- **umr-predicate**（动词头）：`concept` 项输入新概念如 `barbecue-01`；`aspect` 项输入
  `State`/`Activity`/`Endeavor`/`Performance`/`Habitual` 之一。
- **umr-entity**（名词短语）：输入 `ne:disease`（定为命名实体类型）、`head:cancer`
  （改中心词）、或直接输入一个概念。
- **umr-segment**（discourse 切分）：输入 `nosplit`（撤销误判的并列切分）或一个连接词概念。

> 想用模型的判断来 review：`python correct.py review "..." --engine claude`。
> 不过 review 是交互式的，mock 更快，且两种引擎用的是同一套纠正键，所以默认 mock 即可。

### 2b. `correct.py <层> ...`——一条命令记一条纠正

知道要改什么时，直接一条命令（适合脚本化、批量灌入领域知识）：

```bash
# 关系：give-01 下的 "her friend" 是 :recipient 不是 :goal
python correct.py role --head give-01 --child "her friend" --relation :recipient \
       --note "animate receiver"

# 用正则泛化（任意 match 字段加 _regex 后缀）：任何 give.* + 任何含 friend 的成分
python correct.py role --head-regex "give-\d+" --child-regex friend --relation :recipient

# 动词头/aspect：修启发式词元 bug
python correct.py predicate --verb-surface barbecued --concept barbecue-01 --aspect Performance

# 命名实体：tagger 漏掉的多词病名
python correct.py entity --span "bone cancer" --ne-type disease --wiki "Bone_cancer"

# 阻止误判的并列切分（固定搭配）
python correct.py segment --span "rock and roll is here to stay" --no-split
```

非法值会被拒（如 `--relation :bogus`、非法 aspect）。

### 2c. 直接编辑文件

每层一个纯文本文件，手工随便加（`#` 开头是注释）：

```
skills/umr-segment/heuristics.jsonl
skills/umr-predicate/heuristics.jsonl
skills/umr-role/heuristics.jsonl
skills/umr-entity/heuristics.jsonl
```

每行一条规则：

```jsonc
{"match": {"head_concept": "give-01", "child_text": "her friend"},
 "set":   {"relation": ":recipient"},
 "note":  "animate receiver, not spatial goal"}
```

文件**每次解析都重读**，存盘即生效，不用重启。

### 查看已学到的纠正

```bash
python correct.py list            # 全部四层
python correct.py list umr-role   # 只看某层
```

---

## 3. 纠正是怎么生效的

- **mock 引擎**：每层脚本调 `heuristics.match()` 应用覆盖；`--trace` 里会看到
  `[heuristic] <你的备注> -> <结果>` 在生效。
- **claude 引擎**：该层的所有纠正被注入 skill 的 prompt，标为
  *"LEARNED CORRECTIONS（authoritative，OVERRIDE your default judgement）"*，模型照办。

匹配规则：**最具体优先**（满足的 match 条件越多越优先），同级则**最新优先**。

### match / set 键速查

| 层 | match 键（可加 `_regex`） | set 键（改什么） |
|----|--------------------------|-----------------|
| `umr-segment`   | `span` | `no_split: true`、`connective` |
| `umr-predicate` | `span`、`verb`、`verb_surface`、`concept` | `concept`、`aspect`、`modstr` |
| `umr-role`      | `head_concept`、`head_text`、`child_text`、`category`、`relation_hint` | `relation` |
| `umr-entity`    | `span` | `ne_type`、`name`、`wiki`、`concept`、`head`、`ref_number`、`ref_person` |

`*_regex` 表示该字段用正则匹配（大小写不敏感）。例：`{"verb_surface_regex": "^barbecu"}`。

---

## 4. 典型工作流

1. `python harness.py "你的句子" --trace` —— 看 parse 和每步判断。
2. 发现错的地方 → `python correct.py review "你的句子"` 逐条改，或用 `correct.py <层>` 一条条加。
3. 重跑 `harness.py`，确认修好了；trace 里能看到 `[heuristic]` 生效。
4. 攒下来的 `skills/*/heuristics.jsonl` 就是你这个领域的纠错知识库，可纳入版本管理、团队共享。

---

## 5. 跑测试

```bash
python tests/test_smoke.py
```

覆盖：端到端解析、Penman 合法性、标签合法性、JSON 抽取抗噪、以及纠错回路
（规则匹配优先级、role 覆盖、predicate 修词元）。

---

## 6. 说明与边界

- **mock 是启发式演示器，不是 gold 标注器**。简单 SVO、并列、从属、命名实体、代词、
  介词短语它都能对；难的（跨并列项共享主语、控制/提升、词义消歧、细粒度 aspect、
  `-ing` 派生名词）会错——而这正是纠错回路存在的意义：人指出错误，系统记住并泛化。
- 想要真语义精度用 `--engine claude`，同一套 skill 改由模型判断，且同样遵守你的纠正。
- 每个 `skills/<name>/SKILL.md` 都是合法的 Claude Code skill，可拷进 `.claude/skills/`
  单独交互调用某一层。
