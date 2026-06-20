import { useState } from 'react'
import type { PreviewSampleItem } from '../../api/types'
import { api } from '../../api/client'
import { cn } from '../../lib/utils'
import { Film, ImageIcon } from 'lucide-react'

const FAN_LAYOUTS: Record<
  number,
  Array<{ stackRotate: number; spreadRotate: number; spreadX: number; stackY: number; stackX: number; zIndex: number }>
> = {
  2: [
    { stackRotate: -1.5, spreadRotate: -7, spreadX: -12, stackY: 0, stackX: -2, zIndex: 1 },
    { stackRotate: 1.5, spreadRotate: 7, spreadX: 12, stackY: -2, stackX: 2, zIndex: 2 },
  ],
  3: [
    { stackRotate: -2, spreadRotate: -10, spreadX: -16, stackY: 0, stackX: -3, zIndex: 1 },
    { stackRotate: 0, spreadRotate: 0, spreadX: 0, stackY: -2, stackX: 0, zIndex: 2 },
    { stackRotate: 2, spreadRotate: 10, spreadX: 16, stackY: -4, stackX: 3, zIndex: 3 },
  ],
}

interface EntryFanPreviewProps {
  samples: PreviewSampleItem[]
  folderPath: string
  previewType?: string | null
  thumbnailVersion: number
  alt: string
  expanded: boolean
}

function FanCard({
  sample,
  layout,
  expanded,
  thumbnailVersion,
  alt,
}: {
  sample: PreviewSampleItem
  layout: { stackRotate: number; spreadRotate: number; spreadX: number; stackY: number; stackX: number; zIndex: number }
  expanded: boolean
  thumbnailVersion: number
  alt: string
}) {
  const [loaded, setLoaded] = useState(false)
  const src = api.mediaThumbUrl(sample.path, sample.media_type, thumbnailVersion)

  return (
    <div
      className={cn(
        'entry-fan-card absolute inset-0 rounded-[var(--radius-sm)] border border-[var(--color-border)] bg-[var(--color-panel)] shadow-[var(--shadow-sm)] overflow-hidden',
        expanded && 'entry-fan-card--expanded',
      )}
      style={
        {
          zIndex: layout.zIndex,
          '--fan-stack-rotate': `${layout.stackRotate}deg`,
          '--fan-spread-rotate': `${layout.spreadRotate}deg`,
          '--fan-spread-x': `${layout.spreadX}px`,
          '--fan-stack-y': `${layout.stackY}px`,
          '--fan-stack-x': `${layout.stackX}px`,
        } as React.CSSProperties
      }
    >
      {!loaded && <div className="absolute inset-0 skeleton" />}
      <img
        src={src}
        alt={alt}
        draggable={false}
        onDragStart={(e) => e.preventDefault()}
        className={cn('w-full h-full object-cover', loaded ? 'opacity-100' : 'opacity-0')}
        loading="lazy"
        onLoad={() => setLoaded(true)}
        onError={() => setLoaded(true)}
      />
      {sample.media_type === 'video' && (
        <span className="absolute bottom-1 right-1 p-0.5 rounded bg-black/50 text-white">
          <Film className="w-2.5 h-2.5" />
        </span>
      )}
    </div>
  )
}

function SinglePreview({
  folderPath,
  previewType,
  thumbnailVersion,
  alt,
}: {
  folderPath: string
  previewType?: string | null
  thumbnailVersion: number
  alt: string
}) {
  const [loaded, setLoaded] = useState(false)
  const src = api.entryThumbUrl(folderPath, thumbnailVersion)

  return (
    <>
      {!loaded && <div className="absolute inset-0 skeleton" />}
      <img
        src={src}
        alt={alt}
        draggable={false}
        onDragStart={(e) => e.preventDefault()}
        className={cn('w-full h-full object-contain', loaded ? 'opacity-100' : 'opacity-0')}
        loading="lazy"
        onLoad={() => setLoaded(true)}
        onError={() => setLoaded(true)}
      />
      {previewType && (
        <span className="absolute bottom-1.5 right-1.5 p-1 rounded bg-black/50 text-white">
          {previewType === 'video' ? <Film className="w-3 h-3" /> : <ImageIcon className="w-3 h-3" />}
        </span>
      )}
    </>
  )
}

export function EntryFanPreview({
  samples,
  folderPath,
  previewType,
  thumbnailVersion,
  alt,
  expanded,
}: EntryFanPreviewProps) {
  const fanSamples = samples.length >= 2 ? samples.slice(0, 3) : []
  const layout = FAN_LAYOUTS[fanSamples.length]

  if (!layout) {
    return (
      <SinglePreview
        folderPath={folderPath}
        previewType={previewType}
        thumbnailVersion={thumbnailVersion}
        alt={alt}
      />
    )
  }

  return (
    <div className={cn('entry-fan-stack relative z-[1] flex items-center justify-center w-full h-full', expanded && 'entry-fan-stack--expanded')}>
      <div className={cn('entry-fan-anchor relative w-[90%] aspect-[12/8.5]', expanded && 'entry-fan-anchor--expanded')}>
        {fanSamples.map((sample, index) => (
          <FanCard
            key={sample.path}
            sample={sample}
            layout={layout[index]}
            expanded={expanded}
            thumbnailVersion={thumbnailVersion}
            alt={alt}
          />
        ))}
      </div>
    </div>
  )
}
