/** "Add a question" command dialog, opened with `/` or the Add question buttons. */
import {
  Command,
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command'

import { addBlock } from './actions'
import { BLOCK_GROUPS, BLOCK_TYPES } from './block-types'
import { useBuilder, useStore } from './store'

export function InsertCommand() {
  const store = useStore()
  const open = useBuilder((s) => s.inserting)
  return (
    <CommandDialog
      open={open}
      onOpenChange={(next) => store.setInserting(next)}
      title="Add a question"
      description="Search question types and press Enter to add one"
    >
      <Command>
      <CommandInput placeholder="Add a question, for example phone" />
      <CommandList>
        <CommandEmpty>No question type matches.</CommandEmpty>
        {BLOCK_GROUPS.map((group) => (
          <CommandGroup key={group} heading={group}>
            {BLOCK_TYPES.filter((b) => b.group === group).map((b) => {
              const Icon = b.icon
              return (
                <CommandItem
                  key={b.type}
                  value={`${b.label} ${b.keywords}`}
                  disabled={!!b.disabled}
                  onSelect={() => {
                    store.setInserting(false)
                    addBlock(store, b.type)
                  }}
                >
                  <Icon />
                  {b.label}
                  {b.disabled && <span className="ms-auto text-xs text-muted-foreground">{b.disabled}</span>}
                </CommandItem>
              )
            })}
          </CommandGroup>
        ))}
      </CommandList>
      </Command>
    </CommandDialog>
  )
}
