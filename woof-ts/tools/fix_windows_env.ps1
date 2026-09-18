<#
.SYNOPSIS
  Чинит окружение линии woof-ts на Windows 11 и проверяет его.

.DESCRIPTION
  Одна команда вместо ручных правок. Сценарий делает ровно то, что описано в
  knowledge/pitfalls.md (запись «дерево игры и резолвер расширений», 2026-09-18):

    Симптом:  npm run build зелёный, npm test падает с
              «ReferenceError: exports is not defined in ES module scope».
    Причина:  в дереве игры появился СОБРАННЫЙ вывод (.js рядом с .ts). Наши импорты
              игры без расширения, а порядок резолвера противоположный:
              esbuild берёт .ts раньше .js (сборка зелёная), Vite/vitest — .js раньше
              .ts (тесты грузят CJS, а игра объявляет "type": "module").
    Лечение:  дерево игры = клон ИСХОДНИКОВ upstream (в src/sim и headless у upstream
              0 файлов .js при 793 .ts) + resolve.extensions с .ts первым в
              vitest.config.ts. НЕ копия дерева с переименованием .js -> .cjs и НЕ
              алиасы: .cjs остаётся CJS, tsc теряет типы, а сверка фактов уходит
              с upstream на рукописную копию.

  Сценарий идемпотентен: повторный запуск ничего не ломает. Деструктивное действие
  (git clean внутри дерева игры) выполняется только с явным -CleanInPlace; по умолчанию
  загрязнённое дерево не трогается, а рядом кладётся чистый клон и ссылка game
  переводится на него.

.PARAMETER RepoDir
  Каталог линии woof-ts. По умолчанию — родитель каталога tools/, где лежит сценарий.

.PARAMETER GameDir
  Дерево игры. По умолчанию D:\woc-game.

.PARAMETER CleanGameDir
  Куда положить чистый sparse-клон, если GameDir загрязнён собранным выводом.
  По умолчанию "<GameDir>-clean".

.PARAMETER CleanInPlace
  Разрешить деструктивную очистку GameDir (git clean -xd src headless).
  Без этого флага сценарий делает чистый клон рядом и ничего не удаляет в GameDir.

.PARAMETER SkipTests
  Не запускать npm test (только сборка и сверка фактов).

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File tools\fix_windows_env.ps1

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File tools\fix_windows_env.ps1 -GameDir D:\woc-game -CleanInPlace
#>
[CmdletBinding()]
param(
  [string]$RepoDir,
  [string]$GameDir = 'D:\woc-game',
  [string]$CleanGameDir,
  [switch]$CleanInPlace,
  [switch]$SkipTests
)

$ErrorActionPreference = 'Stop'
$script:Results = New-Object System.Collections.ArrayList

function Add-Result {
  param([string]$Step, [string]$Status, [string]$Detail)
  [void]$script:Results.Add([pscustomobject]@{ Шаг = $Step; Статус = $Status; Детали = $Detail })
  $color = 'Gray'
  if ($Status -eq 'OK') { $color = 'Green' }
  elseif ($Status -eq 'ПРОВАЛ') { $color = 'Red' }
  elseif ($Status -eq 'ВНИМАНИЕ') { $color = 'Yellow' }
  Write-Host ("[{0}] {1} — {2}" -f $Status, $Step, $Detail) -ForegroundColor $color
}

function Invoke-Tool {
  # Запуск внешней команды с возвратом stdout+stderr и кода возврата.
  param([string]$Exe, [string[]]$ToolArgs, [string]$WorkDir)
  $prev = (Get-Location).Path
  if ($WorkDir) { Set-Location $WorkDir }
  try {
    $out = & $Exe @ToolArgs 2>&1
    $code = $LASTEXITCODE
    return [pscustomobject]@{ Exit = $code; Out = ($out | Out-String) }
  } finally {
    Set-Location $prev
  }
}

Write-Host '=== woof-ts: починка окружения на Windows ===' -ForegroundColor Cyan

# --- 0. где мы и чем работаем -------------------------------------------------
if (-not $RepoDir) { $RepoDir = Split-Path -Parent $PSScriptRoot }
$RepoDir = (Resolve-Path $RepoDir).Path
if (-not (Test-Path (Join-Path $RepoDir 'package.json'))) {
  Add-Result '0. каталог линии' 'ПРОВАЛ' "в $RepoDir нет package.json — укажи -RepoDir <путь к woof-ts>"
  $script:Results | Format-Table -AutoSize | Out-Host
  exit 1
}
Add-Result '0. каталог линии' 'OK' $RepoDir

$node = Get-Command node -ErrorAction SilentlyContinue
$npm = Get-Command npm -ErrorAction SilentlyContinue
$git = Get-Command git -ErrorAction SilentlyContinue
if (-not $node -or -not $npm) {
  Add-Result '0. Node и npm' 'ПРОВАЛ' 'Node 20+ не найден в PATH: winget install OpenJS.NodeJS.LTS'
  $script:Results | Format-Table -AutoSize | Out-Host
  exit 1
}
$nodeVer = (& node --version) -replace '^v', ''
$nodeMajor = [int]($nodeVer.Split('.')[0])
if ($nodeMajor -lt 20) {
  Add-Result '0. Node и npm' 'ПРОВАЛ' "нужен Node 20+, найден $nodeVer"
  $script:Results | Format-Table -AutoSize | Out-Host
  exit 1
}
Add-Result '0. Node и npm' 'OK' "node $nodeVer, git $(if ($git) { 'есть' } else { 'НЕТ' })"

# --- 1. удалить копию дерева игры (.game-cjs) ---------------------------------
# Копия игры внутри репозитория запрещена: факты берутся импортом из клона upstream.
$gameCjs = Join-Path $RepoDir '.game-cjs'
if (Test-Path $gameCjs) {
  $cnt = (Get-ChildItem -Path $gameCjs -Recurse -File -ErrorAction SilentlyContinue | Measure-Object).Count
  cmd /c "rmdir /s /q `"$gameCjs`"" | Out-Null
  if (Test-Path $gameCjs) {
    Add-Result '1. копия дерева игры' 'ПРОВАЛ' "не удалось удалить $gameCjs ($cnt файлов) — удали вручную и перезапусти"
  } else {
    Add-Result '1. копия дерева игры' 'OK' "удалено $gameCjs ($cnt файлов): факты берутся из upstream, не из копии"
  }
} else {
  Add-Result '1. копия дерева игры' 'OK' '.game-cjs нет'
}

# --- 2. алиасы на копию в конфигах -------------------------------------------
$tsconfig = Join-Path $RepoDir 'tsconfig.json'
if (Test-Path $tsconfig) {
  $tstext = [System.IO.File]::ReadAllText($tsconfig)
  if ($tstext -match 'game-cjs') {
    Add-Result '2. алиасы в tsconfig' 'ВНИМАНИЕ' 'в tsconfig.json остались пути на .game-cjs — убери блок "paths" целиком: типы должны браться из .ts дерева игры'
  } else {
    Add-Result '2. алиасы в tsconfig' 'OK' 'алиасов на копию нет (и не нужно: tsconfig paths не влияют на рантайм vitest)'
  }
}

# --- 3. диагностика дерева игры ----------------------------------------------
if (-not $CleanGameDir) { $CleanGameDir = "$GameDir-clean" }

function Get-StrayJs {
  param([string]$Root)
  $found = @()
  foreach ($sub in @('src\sim', 'headless')) {
    $p = Join-Path $Root $sub
    if (Test-Path $p) {
      $found += Get-ChildItem -Path $p -Recurse -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Extension -eq '.js' -or $_.Extension -eq '.cjs' -or $_.Extension -eq '.mjs' } |
        ForEach-Object { $_.FullName.Substring($Root.Length + 1) }
    }
  }
  return $found
}

$target = $null
if (-not (Test-Path (Join-Path $GameDir 'src\sim'))) {
  Add-Result '3. дерево игры' 'ВНИМАНИЕ' "в $GameDir нет src\sim — нужен клон upstream, делаю чистый клон в $CleanGameDir"
} else {
  $stray = @(Get-StrayJs -Root $GameDir)
  $tsCount = (Get-ChildItem -Path $GameDir -Recurse -File -Filter *.ts -ErrorAction SilentlyContinue | Measure-Object).Count
  if ($stray.Count -eq 0) {
    Add-Result '3. дерево игры' 'OK' "$GameDir чист: .ts=$tsCount, собранных .js/.cjs/.mjs в src\sim и headless нет"
    $target = $GameDir
  } elseif ($CleanInPlace) {
    Add-Result '3. дерево игры' 'ВНИМАНИЕ' "найдено собранных файлов: $($stray.Count) (например $($stray[0])) — очищаю на месте (-CleanInPlace)"
    $dry = Invoke-Tool 'git' @('clean', '-xdn', 'src', 'headless') $GameDir
    Write-Host $dry.Out
    $cl = Invoke-Tool 'git' @('clean', '-xd', 'src', 'headless') $GameDir
    if ($cl.Exit -ne 0) {
      Add-Result '3. дерево игры' 'ПРОВАЛ' "git clean завершился с кодом $($cl.Exit): $($cl.Out)"
    } else {
      $stray2 = @(Get-StrayJs -Root $GameDir)
      if ($stray2.Count -eq 0) {
        Add-Result '3. дерево игры' 'OK' "$GameDir очищен от собранного вывода"
        $target = $GameDir
      } else {
        Add-Result '3. дерево игры' 'ПРОВАЛ' "после git clean осталось $($stray2.Count) .js-файлов — вероятно это не клон git; снеси каталог и запусти сценарий заново (сделает чистый клон)"
      }
    }
  } else {
    Add-Result '3. дерево игры' 'ВНИМАНИЕ' "$GameDir загрязнён собранным выводом: $($stray.Count) файлов .js/.cjs/.mjs (например $($stray[0])). Не трогаю его; сделаю чистый клон в $CleanGameDir. Хочешь очистить на месте — перезапусти с -CleanInPlace"
  }
}

# --- 4. чистый sparse-клон upstream, если нужен -------------------------------
if (-not $target) {
  $repo = 'https://github.com/levy-street/world-of-claudecraft.git'
  if (Test-Path $CleanGameDir) {
    Add-Result '4. чистый клон' 'ВНИМАНИЕ' "$CleanGameDir уже существует — использую как есть (удали каталог, если нужен свежий клон)"
  } else {
    Write-Host "[4. чистый клон] клонирую upstream (sparse, blobless) в $CleanGameDir ..."
    $c1 = Invoke-Tool 'git' @('clone', '--depth', '1', '--filter=blob:none', '--no-checkout', '--branch', 'main', $repo, $CleanGameDir) $null
    if ($c1.Exit -ne 0) {
      Add-Result '4. чистый клон' 'ПРОВАЛ' "git clone код=$($c1.Exit): $($c1.Out)"
      $script:Results | Format-Table -AutoSize | Out-Host
      exit 1
    }
    $c2 = Invoke-Tool 'git' @('sparse-checkout', 'init', '--no-cone') $CleanGameDir
    $patterns = @('/src/sim/**', '/src/world_api.ts', '/src/world_api/**', '/headless/**', '/python/**', '/package.json', '/CLAUDE.md', '/README.md')
    $c3 = Invoke-Tool 'git' (@('sparse-checkout', 'set', '--no-cone') + $patterns) $CleanGameDir
    $c4 = Invoke-Tool 'git' @('read-tree', '-mu', 'HEAD') $CleanGameDir
    if ($c2.Exit -ne 0 -or $c3.Exit -ne 0 -or $c4.Exit -ne 0) {
      Add-Result '4. чистый клон' 'ПРОВАЛ' "sparse-checkout не удался: $($c2.Out) $($c3.Out) $($c4.Out)"
      $script:Results | Format-Table -AutoSize | Out-Host
      exit 1
    }
  }
  if (-not (Test-Path (Join-Path $CleanGameDir 'src\sim\obs.ts'))) {
    Add-Result '4. чистый клон' 'ПРОВАЛ' "в $CleanGameDir нет src\sim\obs.ts — клон неполный"
    $script:Results | Format-Table -AutoSize | Out-Host
    exit 1
  }
  $stray3 = @(Get-StrayJs -Root $CleanGameDir)
  if ($stray3.Count -gt 0) {
    Add-Result '4. чистый клон' 'ПРОВАЛ' "в чистом клоне почему-то есть .js: $($stray3.Count) — сообщи об этом, так быть не должно"
    $script:Results | Format-Table -AutoSize | Out-Host
    exit 1
  }
  $tsCount2 = (Get-ChildItem -Path $CleanGameDir -Recurse -File -Filter *.ts -ErrorAction SilentlyContinue | Measure-Object).Count
  Add-Result '4. чистый клон' 'OK' "$CleanGameDir: .ts=$tsCount2, .js=0 (как в upstream)"
  $target = $CleanGameDir
}

# --- 5. ссылка game -> дерево игры -------------------------------------------
# Junction (mklink /J) не требует прав разработчика, в отличие от символической ссылки.
$link = Join-Path $RepoDir 'game'
if (Test-Path $link) {
  # ВАЖНО: rmdir убирает ТОЛЬКО ссылку. Remove-Item -Recurse на junction в старых
  # версиях PowerShell способен вынести содержимое цели — поэтому только cmd /c rmdir.
  $cur = ''
  try { $cur = (Get-Item $link).Target } catch { $cur = '' }
  cmd /c "rmdir `"$link`"" | Out-Null
  if (Test-Path $link) {
    Add-Result '5. ссылка game' 'ПРОВАЛ' "$link не является ссылкой и не удалился — убери вручную (это должен быть junction на дерево игры)"
    $script:Results | Format-Table -AutoSize | Out-Host
    exit 1
  }
  Write-Host "[5. ссылка game] прежняя ссылка убрана (вела на: $cur)"
}
$mk = cmd /c "mklink /J `"$link`" `"$target`"" 2>&1
if ($LASTEXITCODE -ne 0 -or -not (Test-Path (Join-Path $link 'src\sim\obs.ts'))) {
  Add-Result '5. ссылка game' 'ПРОВАЛ' "mklink /J не удался: $mk"
  $script:Results | Format-Table -AutoSize | Out-Host
  exit 1
}
Add-Result '5. ссылка game' 'OK' "$link -> $target (junction, права разработчика не нужны)"

# --- 6. vitest.config.ts: .ts раньше .js -------------------------------------
$vcfg = Join-Path $RepoDir 'vitest.config.ts'
$vtext = [System.IO.File]::ReadAllText($vcfg)
if ($vtext -match "resolve:\s*\{") {
  Add-Result '6. vitest.config.ts' 'OK' 'resolve.extensions уже задан'
} else {
  $block = @"
  // .ts ДО .js: дефолт Vite ставит .js раньше .ts, а esbuild — наоборот. Если в
  // дереве игры рядом с исходниками лежит собранный вывод, сборка берёт .ts, а
  // тесты — .js (CJS в ESM-области = «exports is not defined in ES module scope»).
  // Факты обязаны браться из исходников upstream; чистоту дерева проверяет
  // tools/verify_facts.ts (секция C).
  resolve: {
    extensions: ['.mts', '.ts', '.tsx', '.mjs', '.js', '.jsx', '.json'],
  },
"@
  $marker = 'export default defineConfig({'
  if ($vtext -notmatch [regex]::Escape($marker)) {
    Add-Result '6. vitest.config.ts' 'ПРОВАЛ' "не нашёл '$marker' — файл переписан вручную, приведи его к виду из репозитория"
  } else {
    $vtext = $vtext.Replace($marker, $marker + "`r`n" + $block)
    [System.IO.File]::WriteAllText($vcfg, $vtext)
    Add-Result '6. vitest.config.ts' 'OK' 'добавлен resolve.extensions с .ts первым'
  }
}

# --- 7. зависимости, сборка, сверка фактов, тесты -----------------------------
if (-not (Test-Path (Join-Path $RepoDir 'node_modules\.bin\vitest.cmd'))) {
  Write-Host '[7. сборка] npm install ...'
  $ni = Invoke-Tool 'npm' @('install', '--no-audit', '--no-fund') $RepoDir
  if ($ni.Exit -ne 0) {
    Add-Result '7. npm install' 'ПРОВАЛ' $ni.Out
    $script:Results | Format-Table -AutoSize | Out-Host
    exit 1
  }
  Add-Result '7. npm install' 'OK' 'зависимости стоят'
} else {
  Add-Result '7. npm install' 'OK' 'зависимости уже стоят'
}

$b = Invoke-Tool 'npm' @('run', 'build') $RepoDir
if ($b.Exit -ne 0) {
  Add-Result '8. npm run build' 'ПРОВАЛ' $b.Out
} else {
  Add-Result '8. npm run build' 'OK' 'dist/run.mjs и dist/tune.mjs собраны'
}

$vf = Invoke-Tool 'npx' @('esbuild', 'tools/verify_facts.ts', '--bundle', '--platform=node', '--format=esm', '--outfile=dist/verify_facts.mjs', '--log-level=warning') $RepoDir
if ($vf.Exit -ne 0) {
  Add-Result '9. сверка фактов' 'ПРОВАЛ' "esbuild не собрал verify_facts: $($vf.Out)"
} else {
  $r = Invoke-Tool 'node' @('dist/verify_facts.mjs') $RepoDir
  Write-Host $r.Out
  if ($r.Exit -ne 0) {
    Add-Result '9. сверка фактов' 'ПРОВАЛ' "дерево игры разошлось с политиками агента (см. вывод выше)"
  } else {
    Add-Result '9. сверка фактов' 'OK' 'факты импортируются из исходников upstream и сходятся'
  }
}

if ($SkipTests) {
  Add-Result '10. npm test' 'ВНИМАНИЕ' 'пропущено (-SkipTests)'
} else {
  Write-Host '[10. npm test] гоняю тесты (настоящая симуляция и настоящий env-сервер, минуты) ...'
  $t = Invoke-Tool 'npm' @('test') $RepoDir
  $tail = ($t.Out -split "`r?`n" | Where-Object { $_ -match 'Test Files|Tests |FAIL|Error' } | Select-Object -Last 8) -join "`n"
  Write-Host $tail
  if ($t.Exit -ne 0) {
    Add-Result '10. npm test' 'ПРОВАЛ' 'тесты красные — см. вывод выше'
  } else {
    Add-Result '10. npm test' 'OK' 'ожидаем: Test Files 6 passed (6), Tests 62 passed (62)'
  }
}

# --- итог ---------------------------------------------------------------------
Write-Host ''
Write-Host '=== ИТОГ ===' -ForegroundColor Cyan
$script:Results | Format-Table -AutoSize | Out-Host
$bad = @($script:Results | Where-Object { $_.Статус -eq 'ПРОВАЛ' })
if ($bad.Count -gt 0) {
  Write-Host "ПРОВАЛОВ: $($bad.Count) — окружение не готово" -ForegroundColor Red
  exit 1
}
Write-Host 'ОКРУЖЕНИЕ ГОТОВО' -ForegroundColor Green
Write-Host 'Полный гейт линии (типы, факты, тесты, стенд, пороги, бридж, контур обучения):'
Write-Host '  bash tools/check_all.sh        (в Git Bash)  — либо по шагам из вывода выше'
exit 0
