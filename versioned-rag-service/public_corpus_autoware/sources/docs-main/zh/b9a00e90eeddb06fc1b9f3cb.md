# 审核提示

## 在 diff 视图中切换注释或查看评论

在审阅期间,差异视图中可能有一些注释或审阅注释.

要切换注释,请按 `A` 键.

以前：

（图片说明：before-press-a；未对图片像素执行 OCR）

后：

（图片说明：after-press-a；未对图片像素执行 OCR）

要切换评论评论,请按 `I` 键.

有关其他键盘快捷键,请参阅 [GitHub Docs](https://docs.github.com/en/get-started/using-github/keyboard-shortcuts).

## 在基于 Web 的 Visual Studio Code 中查看代码

您可以从浏览器打开 `Visual Studio Code` ,以丰富的 UI 查看代码. 要使用它,请在任何存储库或拉取请求上按 `.` 键.

更详细的用法请参考 [github/dev](https://github.com/github/dev).

## 快速签出拉取请求的分支

如果你想签出 Pull Request 的分支,使用 fork-and-pull 模型通常会很麻烦.

```
# Copy the user name and the fork URL.
git remote add {user-name} {fork-url}
git checkout {user-name}/{branch-name}
git remote rm {user-name} # To clean up
```

相反,您可以使用 [GitHub CLI](https://cli.github.com/) 来简化步骤,只需运行 `gh pr checkout {pr-number}` 即可.

您可以从拉取请求页面的右上角复制命令.

（图片说明：gh-pr-checkout；未对图片像素执行 OCR）
