# Prompt OneShot Replacer

このリポジトリには、長文のプロンプトテンプレート内に埋め込まれた OneShot / FewShot 例を別の例文で差し替えるためのユーティリティが含まれています。`prompt_oneshot.replacer` モジュールは、TOML で定義した置換ルールに基づき、指定したテンプレートから対象セクションを検出して新しい例文に置き換えます。

## 使い方

1. `examples/` 配下のような設定ファイル（TOML）を用意します。
   - `prompt_path`: 編集対象のプロンプトファイル。
   - `example_path`: OneShot の元になる例文ファイル。
   - `output_path`: 変更後のプロンプトを書き出すパス（未指定の場合は `prompt_path` を上書き）。
   - `replacements`: 置換ルールの配列。各ルールでプロンプト側の `start_marker` と `end_marker` を指定し、その間のテキストを `source` で抽出した内容に差し替えます。

2. 置換に使う `source` は以下を指定できます。
   - `type = "heading"`: 例文内の Markdown 見出しと一致するセクションを抽出。
   - `type = "heading_list"`: 複数の見出しを順番に取得して結合。
   - `type = "markers"`: 任意の文字列マーカーで囲まれた範囲を抽出。
   - `type = "literal"`: 定数文字列をそのまま挿入。
   - `type = "file"`: 外部ファイルの内容を挿入。

3. コマンド例:

   ```bash
   python -m prompt_oneshot.replacer --config examples/replacements.toml
   ```

   `--prompt`、`--example`、`--output` を指定すると、設定ファイルの値を一時的に上書きできます。`--dry-run` を付けると標準出力に結果を表示するだけでファイルは変更しません。

`examples/` には、レイモンド ウェイル「マエストロ」のレビュー記事をもとにした設定例を収録しています。テンプレート中のレビュー OneShot とユーザーの感想サンプルを、記事内の見出しセクションで置き換える設定になっています。

## テスト

標準ライブラリの `unittest` で動作確認ができます。

```bash
python -m unittest discover -s tests
```
