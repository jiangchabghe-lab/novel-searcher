# APK 打包两种方式

## 方式 A：云端 GitHub Actions（推荐，零本地环境）

### 步骤

1. **在 GitHub 上创建一个新仓库**，并把当前项目推送到 GitHub。
   ```powershell
   # 在项目根目录执行
   git init
   git add .
   git commit -m "init"
   git branch -M main
   git remote add origin https://github.com/<您的用户名>/<仓库名>.git
   git push -u origin main
   ```

2. **打开 GitHub 仓库页面 → Actions 标签页**
   - 看到 "Build APK" 工作流正在运行（通常 5-10 分钟）
   - 构建成功后，点击进入工作流详情

3. **下载 APK**
   - 在工作流详情页底部的 "Artifacts" 区域，点击 `novel-searcher-apk` 下载 zip 包
   - 解压后即可得到 `.apk` 文件
   - 传输到安卓手机安装即可

## 方式 B：本地 WSL2（如果您想完全本地）

### 步骤

1. 按 `Win + R`，输入 `optionalfeatures`，确保勾选以下两项后重启：
   - `Microsoft-Windows-Subsystem-Linux`
   - `VirtualMachinePlatform`

2. 重启后在管理员 PowerShell 执行：
   ```powershell
   wsl --install -d Ubuntu-22.04
   ```

3. 打开 Ubuntu 终端，设置用户名密码后执行：
   ```bash
   cd /mnt/e/.../小说
   ./scripts/setup_buildozer_in_wsl.sh
   ./scripts/build_apk_in_wsl.sh
   ```

4. APK 会自动复制到项目根目录。

## 常见问题

### Q：GitHub Actions 构建失败？
查看工作流日志。常见问题：
- Python 版本不兼容 → 在 `build-apk.yml` 中修改 `python-version`
- 依赖库编译失败 → 查看日志中的 `error:` 行

### Q：如何触发 GitHub Actions 重新构建？
在仓库 Actions 页面，手动点击 "Run workflow"。

### Q：APK 体积太大？
Debug 版通常 25~40MB。如需更小体积：
- 在 `buildozer.spec` 中只保留 `arm64-v8a` 一个架构
- 使用 `buildozer android release` 打包发布版
