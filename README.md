# 国科大慕课答案填充器

参考 `HangboZhu/ucas-mooc-automate` 的 Selenium 使用方式编写。程序读取你准备好的本地答案表，填写当前测验页面中的单选、多选、判断和文本题，并把成功、歧义和未匹配项打印出来。填写成功后会选择页面中的“暂时保存”。

程序**不会搜索或生成答案**。默认只暂时保存；只有显式传入 `--submit` 才会点击并确认提交。页面中绿色边框表示已填写，红色边框表示填写失败；请自行检查每一道题。

## 安装

需要 Python 3.10+ 和 Chrome：

```powershell
python -m pip install -r requirements.txt
```

项目会依次从 `--driver` 参数、`CHROMEDRIVER` 环境变量、系统 `PATH` 和 Selenium 本地缓存中查找 ChromeDriver，找到本地驱动时不会依赖 Selenium Manager 联网。

## 准备答案

复制 `answers.example.json` 为 `answers.json`。每条答案可通过题干 `question`、页面题目 ID `id` 或从 1 开始的题号 `index` 匹配。优先使用完整题干，页面题序固定时才建议使用 `index`。

支持的 `type`：

- `single`：单选，`answer` 可写选项字母或完整选项文字。
- `multiple`：多选，`answer` 必须是数组，例如 `["A", "C"]`。
- `judge`：判断，例如 `"正确"` 或 `"错误"`。
- `text`：填空。多个输入框时可传字符串数组。

选择题可以增加 `answer_text`，让程序在选项顺序被打乱时按文字定位；匹配不到文字时才退回 `answer` 中的字母：

```json
{
  "index": 1,
  "type": "multiple",
  "answer": ["B", "C"],
  "answer_text": ["选项文字一", "选项文字二"]
}
```

只有题号、没有完整题干的答案仍依赖当前测验的题目顺序。如果平台连题目顺序也随机，必须在条目中补充完整 `question` 才能可靠对应。

如果一个文件中包含多个章节，可使用顶层 `answer_sets` 对象保存多个答案组。运行时必须用 `--set` 选择当前页面对应的组：

```powershell
python main.py --answers answers.json --set "1.1章节测验"
```

如果不想依赖题号或 URL 中的 `chapterId`，可使用搜索模式：

```powershell
python main.py --answers answers.json --search
```

搜索模式会遍历当前页面，在题干和选项文字中查找 `question`、`answer_text` 或 `note`；多选题要求全部答案文字匹配。只包含题号和字母、没有任何题干或选项文字的旧条目无法可靠搜索，会报告为未匹配，不会按题号冒险填写。

`answers.json` 还可以用顶层 `chapter_sets` 将 URL 中的 `chapterId` 绑定到答案组。已绑定的章节可省略 `--set`；如果显式传入了冲突答案组，程序会拒绝填写。程序会等你登录并进入测验后，再读取浏览器当前 URL，因此从门户页启动、手动导航到已绑定章节也能自动选择答案组。

## 运行

```powershell
python main.py --answers answers.json
```

浏览器打开后完成登录，进入具体测验页面，等题目出现，再回到终端按回车。程序会在 60 秒内反复检查页面里的 iframe，所以既支持题目直接显示在页面中，也支持加载较慢的嵌套课程页面。填写结束后，程序会在相同的页面和 iframe 范围内查找并点击一次“暂时保存”；找不到按钮时只输出提示，不会改点其他按钮。

填写后浏览器不会关闭。可以在浏览器中切换到下一章节，再回到终端按回车，程序会根据当前 URL 重新选择答案组并继续识别。输入 `q`、`quit`、`exit` 或按 `Ctrl+C` 才会退出并关闭浏览器。

### 自动逐章填写

进入任意一个已经配置 `chapter_sets` 的章节测验后，可以从该章开始自动填写后续测验：

```powershell
python main.py --answers answers.json --auto --profile-dir .chrome-profile
```

登录并打开起始测验后，只需按一次回车。默认模式会填写当前页、点击“暂时保存”，然后通过保留 `courseId`、`clazzid` 和 `enc` 等参数并更新 `chapterId` 的方式进入下一测验。只有当前页全部题目成功匹配且确认操作成功后才会翻页；未匹配、答案组缺失或操作失败时会停在当前页面。只有额外指定 `--submit` 才会改为提交。

可调整章节间等待时间：

```powershell
python main.py --answers answers.json --auto --page-delay 3 --profile-dir .chrome-profile
```

`--auto` 依赖 `chapter_sets` 确保答案组与章节严格对应，因此不能和 `--set` 或 `--search` 同时使用。

确认答案无误后，可让自动模式逐章提交：

```powershell
python main.py --answers answers.json --auto --submit --profile-dir .chrome-profile
```

提交模式会点击真实确认框 `#confirmSubWin` 中的“确定”。每章开始前，程序会先检查“任务点已完成”“查看已批阅作业”“本次成绩/最终成绩”等标志，已提交章节会直接跳过。新提交的章节也必须检测到这些完成页标志或“提交成功”提示后才进入下一章节；没有检测到成功状态时会停在当前章节。提交后通常无法修改，因此 `--submit` 必须显式指定。

如果页面加载需要更久，可以调整等待时间：

```powershell
python main.py --answers answers.json --set "1.1章节测验" --wait 120
```

指定起始页面：

```powershell
python main.py --answers answers.json --url "https://mooc.ucas.edu.cn/..."
```

使用独立 Chrome 配置目录保留登录状态：

```powershell
python main.py --answers answers.json --profile-dir .chrome-profile
```

不要把日常 Chrome 正在使用的用户数据目录传给 `--profile-dir`，否则 Chrome 可能因配置目录被占用而无法启动。

如果自动查找驱动失败，可以显式指定：

```powershell
python main.py --answers answers.json --set "1.1章节测验" --driver "C:\path\to\chromedriver.exe"
```

## 测试

测试会启动无界面 Chrome，在本地夹具页面上验证四类题目的填写、嵌套 iframe、默认暂存和显式提交：

```powershell
python -m unittest discover -s tests -v
```
