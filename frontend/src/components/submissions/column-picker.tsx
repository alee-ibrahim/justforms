/** Column picker for the submissions table (PHASE-3-SCREENS 5). */
import { Columns3Icon } from 'lucide-react'

import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import type { FieldElement, FormLanguage } from '@/schema'

import { RESPONDENT_COLUMN } from './use-columns'

export function ColumnPicker({
  fields,
  ids,
  language,
  onChange,
}: {
  fields: FieldElement[]
  ids: string[]
  language: FormLanguage
  onChange: (ids: string[] | null) => void
}) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="sm">
          <Columns3Icon />
          Columns
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="max-h-96 w-64">
        <DropdownMenuLabel>Show in the table</DropdownMenuLabel>
        <DropdownMenuCheckboxItem
          checked={ids.includes(RESPONDENT_COLUMN)}
          onSelect={(e) => e.preventDefault()}
          onCheckedChange={(on) => onChange(on ? [...ids, RESPONDENT_COLUMN] : ids.filter((x) => x !== RESPONDENT_COLUMN))}
        >
          Respondent email
        </DropdownMenuCheckboxItem>
        <DropdownMenuSeparator />
        {fields.map((f) => (
          <DropdownMenuCheckboxItem
            key={f.id}
            checked={ids.includes(f.id)}
            onSelect={(e) => e.preventDefault()}
            onCheckedChange={(on) => onChange(on ? [...ids, f.id] : ids.filter((x) => x !== f.id))}
          >
            <bdi lang={language} dir="auto" className="truncate">
              {f.label}
            </bdi>
          </DropdownMenuCheckboxItem>
        ))}
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => onChange(null)}>Reset columns</DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
