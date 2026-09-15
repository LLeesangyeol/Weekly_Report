import { readFile } from 'node:fs/promises'
import { parse } from 'kordoc'

const filePath = process.argv[2]
if (!filePath) {
  process.stderr.write('문서 경로가 필요합니다.')
  process.exit(2)
}

try {
  const result = await parse(await readFile(filePath), { tables: true, removeHeaderFooter: true })
  if (!result.success) {
    process.stderr.write(result.error || 'Kordoc 파싱에 실패했습니다.')
    process.exit(1)
  }
  process.stdout.write(result.markdown)
} catch (error) {
  process.stderr.write(error instanceof Error ? error.message : String(error))
  process.exit(1)
}
