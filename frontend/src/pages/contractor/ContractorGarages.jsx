import { useNavigate } from 'react-router-dom'
import Dashboard from '../Dashboard'

export default function ContractorGarages() {
  const navigate = useNavigate()
  const onNav = (id, tab, name) =>
    navigate(`/contractor/garage/${id}?tab=${tab}${name ? '&name=' + encodeURIComponent(name) : ''}`)
  return <Dashboard onNav={onNav} />
}
