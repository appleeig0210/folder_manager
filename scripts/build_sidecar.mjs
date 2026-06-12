import { spawnSync } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const root = path.join(path.dirname(fileURLToPath(import.meta.url)), '..')

function run(command, args) {
  const result = spawnSync(command, args, { stdio: 'inherit', cwd: root, shell: false })
  if (result.error) {
    console.error(result.error.message)
    process.exit(1)
  }
  process.exit(result.status ?? 1)
}

if (process.platform === 'win32') {
  run('powershell', [
    '-ExecutionPolicy',
    'Bypass',
    '-File',
    path.join(root, 'scripts', 'build_sidecar.ps1'),
  ])
} else if (process.platform === 'darwin') {
  run('bash', [path.join(root, 'scripts', 'build_sidecar_macos.sh')])
} else {
  console.error(`Unsupported platform for sidecar build: ${process.platform}`)
  process.exit(1)
}
