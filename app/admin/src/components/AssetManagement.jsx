import { useState, useEffect } from 'react';
import { useMsal } from '@azure/msal-react';
import { projectService } from '../services/projectService';
import '../styles/AssetManagement.css';

const AssetManagement = ({ projectId, projectName }) => {
  const { instance, accounts } = useMsal();
  const account = accounts[0];

  const [assets, setAssets] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [newAssetName, setNewAssetName] = useState('');
  const [newAssetIdentifier, setNewAssetIdentifier] = useState('');
  const [newAssetIsHospitality, setNewAssetIsHospitality] = useState(false);
  const [isCreating, setIsCreating] = useState(false);
  const [uploadingAssetId, setUploadingAssetId] = useState(null);
  const [downloadingAssetFiles, setDownloadingAssetFiles] = useState({});
  const [assetIdFilter, setAssetIdFilter] = useState('');
  const [selectedAssetForEdit, setSelectedAssetForEdit] = useState(null);
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);
  const [editAssetName, setEditAssetName] = useState('');
  const [editAssetIdentifier, setEditAssetIdentifier] = useState('');
  const [editAssetIsHospitality, setEditAssetIsHospitality] = useState(false);
  const [isUpdating, setIsUpdating] = useState(false);

  useEffect(() => {
    fetchAssets();
  }, [projectId]);

  const fetchAssets = async () => {
    try {
      setLoading(true);
      const response = await projectService.getProjectAssets(instance, account, projectId);
      setAssets(response.assets || []);
      setError(null);
    } catch (err) {
      setError(err.message || 'Failed to fetch assets');
      console.error('Error fetching assets:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleCreateAsset = async () => {
    if (!newAssetName.trim()) {
      alert('Please enter an asset name');
      return;
    }
    if (!newAssetIdentifier.trim()) {
      alert('Please enter an asset unique identifier');
      return;
    }

    try {
      setIsCreating(true);
      await projectService.createAsset(instance, account, projectId, {
        asset_unique_identifier: newAssetIdentifier.trim(),
        asset_name: newAssetName.trim(),
        is_hospitality: newAssetIsHospitality,
      });
      setNewAssetName('');
      setNewAssetIdentifier('');
      setNewAssetIsHospitality(false);
      setIsCreateModalOpen(false);
      await fetchAssets();
    } catch (err) {
      alert(`Failed to create asset: ${err.message}`);
      console.error('Error creating asset:', err);
    } finally {
      setIsCreating(false);
    }
  };

  const handleToggleAssetStatus = async (asset) => {
    const action = asset.is_deleted ? 'activate' : 'deactivate';
    const confirmMessage = asset.is_deleted 
      ? 'Are you sure you want to activate this asset?' 
      : 'Are you sure you want to deactivate this asset?';

    if (window.confirm(confirmMessage)) {
      try {
        await projectService.toggleAssetStatus(instance, account, projectId, asset.id, !asset.is_deleted);
        await fetchAssets();
        alert(`Asset ${action}d successfully!`);
      } catch (err) {
        alert(`Failed to ${action} asset: ${err.message}`);
        console.error(`Error ${action} asset:`, err);
      }
    }
  };

  const handleUploadAssetBaseFile = async (assetId, file) => {
    if (!file) {
      return;
    }

    try {
      setUploadingAssetId(assetId);
      await projectService.uploadAssetBaseFile(instance, account, projectId, assetId, file);
      await fetchAssets();
      alert('Asset base file uploaded successfully!');
    } catch (err) {
      alert(`Failed to upload asset base file: ${err.message}`);
      console.error('Error uploading asset base file:', err);
    } finally {
      setUploadingAssetId(null);
    }
  };

  const handleDownloadAssetBaseFile = async (asset) => {
    if (!asset.asset_base_file_link) {
      alert('No base file available for this asset');
      return;
    }

    setDownloadingAssetFiles((prev) => ({ ...prev, [asset.id]: true }));

    try {
      const { url, filename } = await projectService.getAssetBaseFileDownloadUrl(
        instance,
        account,
        projectId,
        asset.id
      );

      const link = document.createElement('a');
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);

      setTimeout(() => {
        window.URL.revokeObjectURL(url);
      }, 100);
    } catch (err) {
      alert(`Failed to download asset base file: ${err.message}`);
      console.error('Error downloading asset base file:', err);
    } finally {
      setDownloadingAssetFiles((prev) => ({ ...prev, [asset.id]: false }));
    }
  };

  const handleEditAsset = (asset) => {
    setSelectedAssetForEdit(asset);
    setEditAssetName(asset.asset_name);
    setEditAssetIdentifier(asset.asset_unique_identifier || '');
    setEditAssetIsHospitality(asset.is_hospitality || false);
    setIsEditModalOpen(true);
  };

  const handleUpdateAsset = async () => {
    if (!editAssetName.trim()) {
      alert('Please enter an asset name');
      return;
    }
    if (!editAssetIdentifier.trim()) {
      alert('Please enter an asset unique identifier');
      return;
    }

    try {
      setIsUpdating(true);
      await projectService.updateAsset(instance, account, projectId, selectedAssetForEdit.id, {
        asset_unique_identifier: editAssetIdentifier.trim(),
        asset_name: editAssetName.trim(),
        is_hospitality: editAssetIsHospitality,
      });
      setIsEditModalOpen(false);
      setSelectedAssetForEdit(null);
      setEditAssetName('');
      setEditAssetIdentifier('');
      await fetchAssets();
    } catch (err) {
      alert(`Failed to update asset: ${err.message}`);
      console.error('Error updating asset:', err);
    } finally {
      setIsUpdating(false);
    }
  };

  const closeCreateModal = () => {
    setIsCreateModalOpen(false);
    setNewAssetName('');
    setNewAssetIdentifier('');
    setNewAssetIsHospitality(false);
  };

  const closeEditModal = () => {
    setIsEditModalOpen(false);
    setSelectedAssetForEdit(null);
    setEditAssetName('');
    setEditAssetIdentifier('');
    setEditAssetIsHospitality(false);
  };

  const filteredAssets = assets.filter((asset) => {
    if (!assetIdFilter.trim()) return true;
    const assetId = (asset.asset_unique_identifier || '').toLowerCase();
    return assetId.includes(assetIdFilter.trim().toLowerCase());
  });

  if (loading) {
    return <div className="asset-management-loading">Loading assets...</div>;
  }

  return (
    <div className="asset-management-container">
      <div className="asset-management-header">
        <h3>Asset Management - {projectName}</h3>
        <button
          className="btn btn-primary"
          onClick={() => setIsCreateModalOpen(true)}
        >
          + Add Asset
        </button>
      </div>

      {error && <div className="error-message">{error}</div>}

      {/* Assets List */}
      <div className="assets-list-section">
        <div className="assets-list-header">
          <h4>
            Project Assets ({filteredAssets.length} of {assets.length})
          </h4>
          <div className="asset-filter">
            <label htmlFor="asset-id-filter">Filter by Asset ID</label>
            <input
              id="asset-id-filter"
              type="text"
              placeholder="Type asset ID..."
              value={assetIdFilter}
              onChange={(e) => setAssetIdFilter(e.target.value)}
            />
          </div>
        </div>
        {filteredAssets.length === 0 ? (
          <div className="no-assets">No assets created yet. Create one to get started.</div>
        ) : (
          <div className="assets-table-container">
            <table className="assets-table">
              <thead>
                <tr>
                  <th>Asset ID</th>
                  <th>Asset Name</th>
                  <th>Base File</th>
                  <th>Created At</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {filteredAssets.map((asset) => (
                  <tr key={asset.id}>
                    <td>{asset.asset_unique_identifier || <span className="no-file">Not set</span>}</td>
                    <td>{asset.asset_name}</td>
                   
                    <td>
                      {asset.asset_base_file_link ? (
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                          <button
                            onClick={() => handleDownloadAssetBaseFile(asset)}
                            disabled={!!downloadingAssetFiles[asset.id]}
                            style={{
                              padding: '4px 8px',
                              backgroundColor: downloadingAssetFiles[asset.id] ? 'var(--color-battleship-gray)' : 'transparent',
                              color: downloadingAssetFiles[asset.id] ? 'var(--color-white)' : 'var(--color-brand-blue)',
                              border: downloadingAssetFiles[asset.id] ? 'none' : '1px solid var(--color-brand-blue)',
                              borderRadius: '4px',
                              cursor: downloadingAssetFiles[asset.id] ? 'not-allowed' : 'pointer',
                              fontSize: '12px',
                              opacity: downloadingAssetFiles[asset.id] ? 0.6 : 1,
                              fontWeight: '500',
                            }}
                          >
                            {downloadingAssetFiles[asset.id] ? 'Loading...' : 'View Template'}
                          </button>

                          <div style={{ position: 'relative' }}>
                            <input
                              id={`asset-replace-${asset.id}`}
                              type="file"
                              accept=".xlsx,.xlsm,.xls,.xlsb"
                              onChange={(e) => {
                                const file = e.target.files?.[0] || null;
                                setUploadingAssetId(file ? asset.id : null);
                                if (file) {
                                  handleUploadAssetBaseFile(asset.id, file);
                                }
                                e.target.value = '';
                              }}
                              style={{
                                position: 'absolute',
                                top: 0,
                                left: 0,
                                width: '100%',
                                height: '100%',
                                opacity: 0,
                                cursor: uploadingAssetId === asset.id ? 'not-allowed' : 'pointer',
                              }}
                              disabled={uploadingAssetId === asset.id || asset.is_deleted}
                            />
                            <button
                              disabled={uploadingAssetId === asset.id || asset.is_deleted}
                              style={{
                                padding: '4px 8px',
                                backgroundColor: uploadingAssetId === asset.id ? 'var(--color-battleship-gray)' : 'var(--color-wisteria)',
                                color: 'var(--color-white)',
                                border: 'none',
                                borderRadius: '4px',
                                cursor: uploadingAssetId === asset.id ? 'not-allowed' : 'pointer',
                                fontSize: '11px',
                                opacity: uploadingAssetId === asset.id ? 0.6 : 1,
                                fontWeight: '500',
                              }}
                            >
                              {uploadingAssetId === asset.id ? '⏳ Replacing...' : '🔄 Replace'}
                            </button>
                          </div>
                        </div>
                      ) : (
                        <div style={{ position: 'relative', display: 'inline-block' }}>
                          <input
                            id={`asset-upload-${asset.id}`}
                            type="file"
                            accept=".xlsx,.xlsm,.xls,.xlsb"
                            onChange={(e) => {
                              const file = e.target.files?.[0] || null;
                              setUploadingAssetId(file ? asset.id : null);
                              if (file) {
                                handleUploadAssetBaseFile(asset.id, file);
                              }
                              e.target.value = '';
                            }}
                            style={{
                              position: 'absolute',
                              top: 0,
                              left: 0,
                              width: '100%',
                              height: '100%',
                              opacity: 0,
                              cursor: uploadingAssetId === asset.id ? 'not-allowed' : 'pointer',
                            }}
                            disabled={uploadingAssetId === asset.id || asset.is_deleted}
                          />
                          <button
                            disabled={uploadingAssetId === asset.id || asset.is_deleted}
                            style={{
                              padding: '4px 8px',
                              backgroundColor: uploadingAssetId === asset.id ? 'var(--color-battleship-gray)' : 'var(--color-light-blue)',
                              color: uploadingAssetId === asset.id ? 'var(--color-white)' : 'var(--color-dark-navy)',
                              border: 'none',
                              borderRadius: '4px',
                              cursor: uploadingAssetId === asset.id ? 'not-allowed' : 'pointer',
                              fontSize: '11px',
                              opacity: uploadingAssetId === asset.id ? 0.6 : 1,
                              fontWeight: '500',
                            }}
                          >
                            {uploadingAssetId === asset.id ? '⏳ Uploading...' : '📤 Upload'}
                          </button>
                        </div>
                      )}
                    </td>
                    <td>{new Date(asset.created_at).toLocaleDateString()}</td>
                    <td>
                      <div className="action-buttons">
                        <button
                          className="btn btn-sm btn-secondary"
                          onClick={() => handleEditAsset(asset)}
                          disabled={asset.is_deleted}
                        >
                          Edit
                        </button>
                        <button
                          className={`btn btn-sm ${asset.is_deleted ? 'btn-success' : 'btn-warning'}`}
                          onClick={() => handleToggleAssetStatus(asset)}
                        >
                          {asset.is_deleted ? 'Activate' : 'Deactivate'}
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Create Asset Modal */}
      {isCreateModalOpen && (
        <div className="modal-overlay">
          <div className="modal-dialog">
            <div className="modal-header">
              <h5>Create New Asset</h5>
              <button
                className="close-btn"
                onClick={closeCreateModal}
              >
                ×
              </button>
            </div>
            <div className="modal-body">
              <div style={{ marginBottom: '15px' }}>
                <label style={{ display: 'block', marginBottom: '5px', fontSize: '14px', fontWeight: '500', color: 'var(--text-primary)' }}>
                  Asset Unique Identifier *
                </label>
                <input
                  type="text"
                  placeholder="e.g., S2-CE-RI-RU-SF-VIL1-0001"
                  value={newAssetIdentifier}
                  onChange={(e) => setNewAssetIdentifier(e.target.value)}
                  className="form-input"
                />
              </div>
              <div>
                <label style={{ display: 'block', marginBottom: '5px', fontSize: '14px', fontWeight: '500', color: 'var(--text-primary)' }}>
                  Asset Name *
                </label>
                <input
                  type="text"
                  placeholder="Enter asset name"
                  value={newAssetName}
                  onChange={(e) => setNewAssetName(e.target.value)}
                  className="form-input"
                />
              </div>
              <div style={{ marginTop: '15px' }}>
                <label style={{ display: 'flex', alignItems: 'center', fontSize: '14px', fontWeight: '500', color: 'var(--text-primary)', cursor: 'pointer' }}>
                  <input
                    type="checkbox"
                    checked={newAssetIsHospitality}
                    onChange={(e) => setNewAssetIsHospitality(e.target.checked)}
                    style={{ marginRight: '8px', cursor: 'pointer' }}
                  />
                  Hospitality Asset
                </label>
              </div>
            </div>
            <div className="modal-footer">
              <button
                className="btn btn-secondary"
                onClick={closeCreateModal}
              >
                Cancel
              </button>
              <button
                className="btn btn-primary"
                onClick={handleCreateAsset}
                disabled={isCreating}
              >
                {isCreating ? 'Creating...' : 'Create'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Edit Asset Modal */}
      {isEditModalOpen && (
        <div className="modal-overlay">
          <div className="modal-dialog">
            <div className="modal-header">
              <h5>Edit Asset</h5>
              <button
                className="close-btn"
                onClick={closeEditModal}
              >
                ×
              </button>
            </div>
            <div className="modal-body">
              <div style={{ marginBottom: '15px' }}>
                <label style={{ display: 'block', marginBottom: '5px', fontSize: '14px', fontWeight: '500', color: 'var(--text-primary)' }}>
                  Asset Unique Identifier *
                </label>
                <input
                  type="text"
                  placeholder="e.g., S2-CE-RI-RU-SF-VIL1-0001"
                  value={editAssetIdentifier}
                  onChange={(e) => setEditAssetIdentifier(e.target.value)}
                  className="form-input"
                />
              </div>
              <div>
                <label style={{ display: 'block', marginBottom: '5px', fontSize: '14px', fontWeight: '500', color: 'var(--text-primary)' }}>
                  Asset Name *
                </label>
                <input
                  type="text"
                  placeholder="Enter asset name"
                  value={editAssetName}
                  onChange={(e) => setEditAssetName(e.target.value)}
                  className="form-input"
                />
              </div>
              <div style={{ marginTop: '15px' }}>
                <label style={{ display: 'flex', alignItems: 'center', fontSize: '14px', fontWeight: '500', color: 'var(--text-primary)', cursor: 'pointer' }}>
                  <input
                    type="checkbox"
                    checked={editAssetIsHospitality}
                    onChange={(e) => setEditAssetIsHospitality(e.target.checked)}
                    style={{ marginRight: '8px', cursor: 'pointer' }}
                  />
                  Hospitality Asset
                </label>
              </div>
            </div>
            <div className="modal-footer">
              <button
                className="btn btn-secondary"
                onClick={closeEditModal}
              >
                Cancel
              </button>
              <button
                className="btn btn-primary"
                onClick={handleUpdateAsset}
                disabled={isUpdating}
              >
                {isUpdating ? 'Updating...' : 'Update'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default AssetManagement;
