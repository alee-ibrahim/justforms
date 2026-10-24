import { Kbd, KbdGroup } from '@/components/ui/kbd'
import { BUILDER_SHORTCUTS } from '@/lib/shortcuts'

export function ShortcutList() {
  return (
    <dl className="grid grid-cols-[1fr_auto] items-center gap-x-4 gap-y-1.5 text-sm">
      {BUILDER_SHORTCUTS.map((s) => (
        <div key={s.action} className="contents">
          <dt className="text-muted-foreground">{s.action}</dt>
          <dd>
            <KbdGroup>
              {s.keys.map((k) => (
                <Kbd key={k}>{k}</Kbd>
              ))}
            </KbdGroup>
          </dd>
        </div>
      ))}
    </dl>
  )
}
