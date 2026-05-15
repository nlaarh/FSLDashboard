import { useState } from 'react'
import { createPortal } from 'react-dom'
import { ExternalLink, ImageOff, X, ChevronLeft, ChevronRight } from 'lucide-react'
import { clsx } from 'clsx'

function openPopup(url) {
  window.open(url, 'sfphoto', 'width=1100,height=800,left=100,top=50,resizable=yes,scrollbars=yes')
}

// Lightbox modal — rendered via portal at document.body to escape stacking contexts
function Lightbox({ photos, startIdx, onClose }) {
  const [idx, setIdx] = useState(startIdx)
  const photo = photos[idx]
  const hasPrev = idx > 0
  const hasNext = idx < photos.length - 1

  return createPortal(
    <div
      className="fixed inset-0 bg-black/90 flex items-center justify-center"
      style={{ zIndex: 9999 }}
      onClick={onClose}
    >
      {/* Close */}
      <button
        className="absolute top-4 right-4 text-white/70 hover:text-white z-10"
        onClick={onClose}
      >
        <X className="w-6 h-6" />
      </button>

      {/* Counter */}
      {photos.length > 1 && (
        <div className="absolute top-4 left-1/2 -translate-x-1/2 text-[11px] text-white/60">
          {idx + 1} / {photos.length}
        </div>
      )}

      {/* Prev */}
      {hasPrev && (
        <button
          className="absolute left-4 text-white/60 hover:text-white z-10 bg-black/40 rounded-full p-1"
          onClick={e => { e.stopPropagation(); setIdx(i => i - 1) }}
        >
          <ChevronLeft className="w-7 h-7" />
        </button>
      )}

      {/* Image */}
      <div className="relative max-w-[90vw] max-h-[90vh]" onClick={e => e.stopPropagation()}>
        <img
          src={photo.url}
          alt={photo.title || `Photo ${idx + 1}`}
          className="max-w-[90vw] max-h-[85vh] object-contain rounded-lg shadow-2xl"
        />
        {photo.title && (
          <div className="absolute bottom-0 left-0 right-0 bg-black/60 text-white text-[11px] px-3 py-1.5 rounded-b-lg truncate">
            {photo.title}
          </div>
        )}
        <a
          href={photo.url} target="_blank" rel="noopener noreferrer"
          className="absolute top-2 right-2 bg-black/50 hover:bg-black/80 text-white/70 hover:text-white rounded p-1 transition-colors"
          title="Open full size"
        >
          <ExternalLink className="w-3.5 h-3.5" />
        </a>
      </div>

      {/* Next */}
      {hasNext && (
        <button
          className="absolute right-4 text-white/60 hover:text-white z-10 bg-black/40 rounded-full p-1"
          onClick={e => { e.stopPropagation(); setIdx(i => i + 1) }}
        >
          <ChevronRight className="w-7 h-7" />
        </button>
      )}
    </div>,
    document.body
  )
}

function PhotoThumbnail({ url, title, idx, onOpen }) {
  const [err, setErr] = useState(false)

  if (err) {
    return (
      <button
        onClick={() => openPopup(url)}
        className="flex items-center gap-1.5 text-[10px] text-brand-400 hover:text-brand-300 hover:underline py-0.5 text-left"
      >
        <ExternalLink className="w-3 h-3 shrink-0" />
        {title || `Photo ${idx + 1}`} ↗
      </button>
    )
  }

  return (
    <button
      onClick={() => onOpen(idx)}
      title={title || `Photo ${idx + 1}`}
      className="block w-full rounded-lg overflow-hidden border border-slate-700/40 hover:border-brand-500/60 transition-colors bg-slate-800/40 cursor-zoom-in"
    >
      <img
        src={url}
        alt={title || `Photo ${idx + 1}`}
        onError={() => setErr(true)}
        className="w-full h-20 object-cover"
      />
      {title && (
        <div className="px-1.5 py-0.5 text-[9px] text-slate-500 truncate text-left">{title}</div>
      )}
    </button>
  )
}

function SectionHeader({ label, sfUrl }) {
  return (
    <div className="flex items-center gap-1.5 mb-1">
      <div className="text-[9px] text-slate-600 uppercase tracking-wider">{label}</div>
      {sfUrl && (
        <button
          onClick={() => openPopup(sfUrl)}
          className="text-[9px] text-slate-600 hover:text-brand-400 transition-colors"
        >
          (view in SF ↗)
        </button>
      )}
    </div>
  )
}

function FleetPhotoThumb({ url, title, idx, versionId, onOpen }) {
  const [err, setErr] = useState(false)
  const proxyUrl = versionId ? `/api/accounting/sf-photo/${versionId}` : null

  if (!proxyUrl || err) {
    return (
      <button
        onClick={() => openPopup(url)}
        className="flex items-center gap-1.5 text-[10px] text-brand-400 hover:text-brand-300 hover:underline py-0.5 text-left"
      >
        <ExternalLink className="w-3 h-3 shrink-0" />
        {title || `Photo ${idx + 1}`} ↗
      </button>
    )
  }

  return (
    <button
      onClick={onOpen}
      title={title || `Photo ${idx + 1}`}
      className="block w-full rounded-lg overflow-hidden border border-slate-700/40 hover:border-brand-500/60 transition-colors bg-slate-800/40 cursor-zoom-in"
    >
      <img
        src={proxyUrl}
        alt={title || `Photo ${idx + 1}`}
        onError={() => setErr(true)}
        className="w-full h-20 object-cover"
      />
      {title && (
        <div className="px-1.5 py-0.5 text-[9px] text-slate-500 truncate text-left">{title}</div>
      )}
    </button>
  )
}

export default function AccountingPhotosCard({ photos, code }) {
  const [lightbox, setLightbox] = useState(null) // { photos, startIdx }

  if (!photos) return null

  const isTowbook = photos.type === 'towbook'
  const isE1 = code === 'E1'

  // Towbook — thumbnails for direct Photo_URL__c, popup for SF fallback
  if (isTowbook) {
    const list = photos.photos || []
    const hasPhotos = list.length > 0
    const directList = list.filter(p => p.direct)
    const hasDirect = directList.length > 0

    return (
      <>
        {lightbox && (
          <Lightbox
            photos={lightbox.photos}
            startIdx={lightbox.startIdx}
            onClose={() => setLightbox(null)}
          />
        )}
        <div className="glass rounded-xl border border-slate-700/30 p-4 space-y-2">
          <div className="flex items-center gap-2">
            <div className="text-[10px] text-slate-500 uppercase tracking-wider font-bold">
              Service Photos
              {hasPhotos && <span className="ml-1 text-slate-600 font-normal normal-case">({list.length})</span>}
            </div>
            {photos.error && <span className="text-[9px] text-amber-500 normal-case">(unavailable)</span>}
          </div>
          {photos.error ? (
            <div className="text-[10px] text-slate-600 italic">Could not load photos</div>
          ) : hasPhotos ? (
            hasDirect ? (
              <div className="grid grid-cols-2 gap-2">
                {list.map((p, i) =>
                  p.direct ? (
                    <PhotoThumbnail
                      key={i}
                      url={p.url}
                      title={p.title}
                      idx={i}
                      onOpen={startIdx => setLightbox({ photos: list.filter(x => x.direct), startIdx: list.filter(x => x.direct).findIndex(x => x.url === p.url) })}
                    />
                  ) : (
                    <button
                      key={i}
                      onClick={() => openPopup(p.url)}
                      className="flex items-center gap-1.5 text-[10px] text-brand-400 hover:text-brand-300 hover:underline py-0.5 text-left"
                    >
                      <ExternalLink className="w-3 h-3 shrink-0" />
                      {p.title || `Photo ${i + 1}`} ↗
                    </button>
                  )
                )}
              </div>
            ) : (
              <div className="space-y-0.5">
                {list.map((p, i) => (
                  <button
                    key={i}
                    onClick={() => openPopup(p.url)}
                    className="flex items-center gap-1.5 text-[10px] text-brand-400 hover:text-brand-300 hover:underline py-0.5 text-left"
                  >
                    <ExternalLink className="w-3 h-3 shrink-0" />
                    {p.title || `Photo ${i + 1}`} ↗
                  </button>
                ))}
              </div>
            )
          ) : (
            <div className="flex items-center gap-1.5 text-[10px] text-slate-600 italic">
              <ImageOff className="w-3.5 h-3.5" /> No photos on record
            </div>
          )}
        </div>
      </>
    )
  }

  // On-Platform — pickup (WOLI 00000001) and drop-off (WOLI 00000002)
  const hasPickup = (photos.pickup_photos?.length || 0) > 0
  const hasDropoff = (photos.dropoff_photos?.length || 0) > 0
  const allFleet = [...(photos.pickup_photos || []), ...(photos.dropoff_photos || [])]
  const fleetDirect = allFleet.filter(p => p.version_id)

  function _fleetLightboxIdx(list, p) {
    const directInList = list.filter(x => x.version_id)
    return directInList.findIndex(x => x.version_id === p.version_id)
  }

  return (
    <>
      {lightbox && (
        <Lightbox
          photos={lightbox.photos}
          startIdx={lightbox.startIdx}
          onClose={() => setLightbox(null)}
        />
      )}
      <div className="glass rounded-xl border border-slate-700/30 p-4 space-y-3">
        <div className="flex items-center gap-2">
          <div className="text-[10px] text-slate-500 uppercase tracking-wider font-bold">Service Photos</div>
          {photos.error && <span className="text-[9px] text-amber-500 normal-case">(unavailable)</span>}
        </div>

        {photos.error ? (
          <div className="text-[10px] text-slate-600 italic">Could not load photos</div>
        ) : (
          <div className="space-y-3">
            <div>
              <SectionHeader label="Service / Pickup Photos" sfUrl={photos.woli_01_sf_url} />
              {hasPickup ? (
                <div className="grid grid-cols-2 gap-2">
                  {photos.pickup_photos.map((p, i) => (
                    <FleetPhotoThumb
                      key={i} url={p.url} title={p.title} idx={i} versionId={p.version_id}
                      onOpen={() => setLightbox({
                        photos: fleetDirect.map(x => ({ url: `/api/accounting/sf-photo/${x.version_id}`, title: x.title })),
                        startIdx: Math.max(0, _fleetLightboxIdx(photos.pickup_photos, p)),
                      })}
                    />
                  ))}
                </div>
              ) : (
                <div className="text-[10px] text-slate-600 italic">No photos</div>
              )}
            </div>

            <div>
              <SectionHeader label="Tow Drop-Off Photos" sfUrl={photos.woli_02_sf_url} />
              {hasDropoff ? (
                <div className="grid grid-cols-2 gap-2">
                  {photos.dropoff_photos.map((p, i) => (
                    <FleetPhotoThumb
                      key={i} url={p.url} title={p.title} idx={i} versionId={p.version_id}
                      onOpen={() => setLightbox({
                        photos: fleetDirect.map(x => ({ url: `/api/accounting/sf-photo/${x.version_id}`, title: x.title })),
                        startIdx: Math.max(0, _fleetLightboxIdx(photos.dropoff_photos, p)),
                      })}
                    />
                  ))}
                </div>
              ) : (
                <div className={clsx(
                  'text-[10px]',
                  isE1 ? 'text-red-400 font-semibold' : 'text-slate-600 italic',
                )}>
                  {isE1
                    ? '⚠ No drop-off photos — required for E1 claims > 14 min'
                    : 'No photos'}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </>
  )
}
