// Global state
let currentData = null;
let currentStep = 0;
let isPlaying = false;
let playInterval = null;
let allFolders = [];
let currentDisplayedFolders = [];
let playSpeed = 1000; // Default 1 second
const GRAPH_HEIGHT = 330;
const GRAPH_NODE_RADIUS = 40;

// API configuration
// Use relative path so it works both locally and in production
const API_BASE = '/api';

// DOM elements
const elements = {
    folderList: document.getElementById('folderList'),
    searchBox: document.getElementById('searchBox'),
    playBtn: document.getElementById('playBtn'),
    pauseBtn: document.getElementById('pauseBtn'),
    resetBtn: document.getElementById('resetBtn'),
    prevBtn: document.getElementById('prevBtn'),
    nextBtn: document.getElementById('nextBtn'),
    speedSelect: document.getElementById('speedSelect'),
    currentStepSpan: document.getElementById('currentStep'),
    totalStepsSpan: document.getElementById('totalSteps'),
    currentAction: document.getElementById('currentAction'),
    causalGraph: document.getElementById('causalGraph'),
    hypothesisGraph: document.getElementById('hypothesisGraph'),
    hypothesisGraphTitle: document.getElementById('hypothesisGraphTitle'),
    propertiesTable: document.getElementById('propertiesTable'),
    metricsChart: document.getElementById('metricsChart'),
    metricsChartFrequency: document.getElementById('metricsChartFrequency'),
    metricsChartWeight: document.getElementById('metricsChartWeight')
};

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    loadFolders();
    setupEventListeners();
});

// Setup event listeners
function setupEventListeners() {
    elements.playBtn.addEventListener('click', play);
    elements.pauseBtn.addEventListener('click', pause);
    elements.resetBtn.addEventListener('click', reset);
    elements.prevBtn.addEventListener('click', previousStep);
    elements.nextBtn.addEventListener('click', nextStep);
    elements.speedSelect.addEventListener('change', (e) => {
        playSpeed = parseInt(e.target.value);
        if (isPlaying) {
            pause();
            play();
        }
    });
    elements.searchBox.addEventListener('input', filterFolders);
    
    // Handle window resize
    let resizeTimeout;
    window.addEventListener('resize', () => {
        clearTimeout(resizeTimeout);
        resizeTimeout = setTimeout(() => {
            if (currentData) {
                drawEdgeMetricsCharts();
                updateMetricsChartHighlight();
            }
        }, 250);
    });
}

// Load folder list
async function loadFolders() {
    try {
        const response = await fetch(`${API_BASE}/folders`);
        const result = await response.json();
        
        if (result.success) {
            allFolders = result.folders;
            displayFolders(allFolders);
        } else {
            showError('Failed to load folders: ' + result.error);
        }
    } catch (error) {
        showError('Network error: ' + error.message);
    }
}

// Display folder list
function displayFolders(folders) {
    currentDisplayedFolders = folders;
    if (folders.length === 0) {
        elements.folderList.innerHTML = '<div class="no-data">No experiments found</div>';
        return;
    }
    
    elements.folderList.innerHTML = folders.map((folder, index) => {
        const statusIcon = folder.completed 
            ? '<span class="status-icon completed" title="Completed">✓</span>' 
            : '<span class="status-icon incomplete" title="Incomplete">✗</span>';
        
        return `
            <div class="folder-item" data-index="${index}" onclick="selectFolder(${index})">
                ${statusIcon}
                <span class="folder-name">${folder.relative_path}</span>
            </div>
        `;
    }).join('');
}

// Filter folders
function filterFolders() {
    const query = elements.searchBox.value.toLowerCase();
    const filtered = allFolders.filter(folder => 
        folder.relative_path.toLowerCase().includes(query)
    );
    displayFolders(filtered);
}

// Select folder
async function selectFolder(index) {
    const folder = currentDisplayedFolders[index];
    
    // Update UI selection state
    document.querySelectorAll('.folder-item').forEach(item => {
        item.classList.remove('selected');
    });
    document.querySelector(`.folder-item[data-index="${index}"]`).classList.add('selected');
    
    // Load data
    await loadVisualizationData(folder);
}

// Load visualization data
async function loadVisualizationData(folder) {
    try {
        elements.currentAction.innerHTML = '<div class="loading">Loading...</div>';
        
        const response = await fetch(`${API_BASE}/visualize`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                tracking_file: folder.tracking,
                config_file: folder.config
            })
        });
        
        const result = await response.json();
        
        if (result.success) {
            currentData = result.data;
            currentStep = 0;
            initializeVisualization();
        } else {
            showError('Failed to load data: ' + result.error);
        }
    } catch (error) {
        showError('Network error: ' + error.message);
    }
}

// Initialize visualization
function initializeVisualization() {
    if (!currentData) return;
    
    // Enable control buttons
    elements.playBtn.disabled = false;
    elements.resetBtn.disabled = false;
    elements.nextBtn.disabled = false;
    
    // Update step display
    elements.totalStepsSpan.textContent = currentData.action_chain.length;
    
    // Draw causal graph
    drawCausalGraph();
    drawHypothesisGraph();
    
    // Draw edge metrics charts
    drawEdgeMetricsCharts();
    
    // Show initial state
    updateVisualization();
}

function getCurrentHypothesisAtStep(step) {
    if (!currentData || !currentData.hypothesis_timeline) {
        return null;
    }
    const timeline = currentData.hypothesis_timeline;
    if (!timeline || timeline.length === 0) {
        return null;
    }

    let latest = timeline[0];
    timeline.forEach(item => {
        if (item.action_step <= step) {
            latest = item;
        }
    });
    return latest;
}

function drawHypothesisGraph() {
    const svg = d3.select('#hypothesisGraph');
    svg.selectAll('*').remove();
    if (!currentData) {
        return;
    }

    const width = elements.hypothesisGraph.clientWidth;
    const height = GRAPH_HEIGHT;
    const nodeRadius = GRAPH_NODE_RADIUS;
    const padding = 30;
    svg.attr('width', width).attr('height', height);

    const graph = currentData.graph;
    const nodes = Object.keys(graph.nodes).map(key => ({
        id: key,
        ...graph.nodes[key]
    }));

    const currentHypothesis = getCurrentHypothesisAtStep(currentStep);
    const hypothesisEdges = currentHypothesis ? (currentHypothesis.edges || []) : [];
    const trueEdgeSet = new Set((graph.edges || []).map(e => `${e.from}->${e.to}`));

    const nodeMap = new Map(nodes.map(n => [n.id, n]));
    const links = hypothesisEdges
        .filter(edge => nodeMap.has(edge.from) && nodeMap.has(edge.to))
        .map(edge => ({
            source: nodeMap.get(edge.from),
            target: nodeMap.get(edge.to),
            isTrueEdge: trueEdgeSet.has(`${edge.from}->${edge.to}`)
        }));

    const nodeCount = nodes.length;
    const centerX = width / 2;
    const centerY = height / 2;
    const availableWidth = width - 2 * padding - 2 * nodeRadius;
    const availableHeight = height - 2 * padding - 2 * nodeRadius;
    const minDimension = Math.min(availableWidth, availableHeight);
    const baseRadius = minDimension / 2;
    const radius = Math.max(baseRadius * 0.8, nodeRadius * 2.5);

    nodes.forEach((node, i) => {
        const angle = (2 * Math.PI * i) / nodeCount - Math.PI / 2;
        node.x = centerX + radius * Math.cos(angle);
        node.y = centerY + radius * Math.sin(angle);
    });

    const transformGroup = svg.append('g');
    const linkGroup = transformGroup.append('g');
    const link = linkGroup.selectAll('g')
        .data(links)
        .enter()
        .append('g')
        .attr('class', 'link-group');

    link.append('path')
        .attr('class', 'link')
        .attr('stroke', d => d.isTrueEdge ? '#22c55e' : '#ef4444')
        .attr('stroke-width', 3)
        .attr('fill', 'none')
        .attr('stroke-linecap', 'round')
        .attr('stroke-linejoin', 'round')
        .attr('opacity', 0.95);

    const node = transformGroup.append('g')
        .selectAll('g')
        .data(nodes)
        .enter()
        .append('g')
        .attr('class', 'node controllable');

    node.append('circle')
        .attr('r', nodeRadius)
        .attr('cx', d => d.x)
        .attr('cy', d => d.y)
        .attr('fill', '#6366f1');

    node.append('text')
        .attr('class', 'node-label')
        .attr('text-anchor', 'middle')
        .attr('x', d => d.x)
        .attr('y', d => d.y)
        .attr('dy', '0.2em')
        .text(d => d.property_name || d.id);

    link.select('path').attr('d', d => {
        const dx = d.target.x - d.source.x;
        const dy = d.target.y - d.source.y;
        const angle = Math.atan2(dy, dx);
        const dist = Math.sqrt(dx * dx + dy * dy);

        const sourceX = d.source.x + nodeRadius * Math.cos(angle);
        const sourceY = d.source.y + nodeRadius * Math.sin(angle);
        const arrowLength = 12;
        const lineEndX = d.target.x - (nodeRadius + arrowLength) * Math.cos(angle);
        const lineEndY = d.target.y - (nodeRadius + arrowLength) * Math.sin(angle);
        const dr = dist * 1.5;
        let path = `M${sourceX},${sourceY}A${dr},${dr} 0 0,1 ${lineEndX},${lineEndY}`;

        const arrowWidth = 7;
        const arrow1X = lineEndX - arrowLength * Math.cos(angle) + arrowWidth * Math.sin(angle);
        const arrow1Y = lineEndY - arrowLength * Math.sin(angle) - arrowWidth * Math.cos(angle);
        path += `M${arrow1X},${arrow1Y}L${lineEndX},${lineEndY}`;
        const arrow2X = lineEndX - arrowLength * Math.cos(angle) - arrowWidth * Math.sin(angle);
        const arrow2Y = lineEndY - arrowLength * Math.sin(angle) + arrowWidth * Math.cos(angle);
        path += `M${arrow2X},${arrow2Y}L${lineEndX},${lineEndY}`;
        return path;
    });

    if (elements.hypothesisGraphTitle) {
        const correct = currentHypothesis ? currentHypothesis.num_correct : 0;
        const total = currentHypothesis ? currentHypothesis.num_true : (graph.edges || []).length;
        elements.hypothesisGraphTitle.textContent =
            `Model Hypothesis Graph (correct edges: ${correct}/${total})`;
    }
}

// Draw causal graph
function drawCausalGraph() {
    const svg = d3.select('#causalGraph');
    svg.selectAll('*').remove();
    
    const width = elements.causalGraph.clientWidth;
    const height = GRAPH_HEIGHT;
    const nodeRadius = GRAPH_NODE_RADIUS;
    const padding = 30; // Padding around the graph
    
    svg.attr('width', width).attr('height', height);
    
    const graph = currentData.graph;
    
    // Prepare node data
    const nodes = Object.keys(graph.nodes).map(key => ({
        id: key,
        ...graph.nodes[key]
    }));
    
    // Prepare edge data with node references
    const nodeMap = new Map(nodes.map(n => [n.id, n]));
    const links = graph.edges.map(edge => ({
        source: nodeMap.get(edge.from),
        target: nodeMap.get(edge.to)
    }));
    
    // Calculate static positions using improved circular layout
    const nodeCount = nodes.length;
    const centerX = width / 2;
    const centerY = height / 2;
    
    // Calculate radius to fit all nodes with padding
    // Use a formula that ensures nodes don't overlap and accounts for node count
    const availableWidth = width - 2 * padding - 2 * nodeRadius;
    const availableHeight = height - 2 * padding - 2 * nodeRadius;
    const minDimension = Math.min(availableWidth, availableHeight);
    
    // For many nodes, use a larger radius to spread them out
    // For few nodes, use a smaller radius to keep them compact
    const baseRadius = minDimension / 2;
    const radius = Math.max(
        baseRadius * 0.8, // Use 80% of available space
        nodeRadius * 2.5 // Minimum spacing between nodes
    );
    
    // Distribute nodes in a circle
    nodes.forEach((node, i) => {
        const angle = (2 * Math.PI * i) / nodeCount - Math.PI / 2; // Start from top
        node.x = centerX + radius * Math.cos(angle);
        node.y = centerY + radius * Math.sin(angle);
    });
    
    // Calculate bounding box of all nodes
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    nodes.forEach(node => {
        minX = Math.min(minX, node.x - nodeRadius);
        minY = Math.min(minY, node.y - nodeRadius);
        maxX = Math.max(maxX, node.x + nodeRadius);
        maxY = Math.max(maxY, node.y + nodeRadius);
    });
    
    // Calculate scale and translation to fit all nodes in viewport
    const graphWidth = maxX - minX;
    const graphHeight = maxY - minY;
    const scaleX = (width - 2 * padding) / graphWidth;
    const scaleY = (height - 2 * padding) / graphHeight;
    const scale = Math.min(scaleX, scaleY, 1); // Don't scale up, only down
    
    const offsetX = (width - (maxX + minX) * scale) / 2;
    const offsetY = (height - (maxY + minY) * scale) / 2;
    
    // Apply transform to fit all nodes
    const transformGroup = svg.append('g')
        .attr('transform', `translate(${offsetX},${offsetY}) scale(${scale})`);
    
    // Draw edges with integrated arrows (single path element)
    const linkGroup = transformGroup.append('g');
    const link = linkGroup.selectAll('g')
        .data(links)
        .enter()
        .append('g')
        .attr('class', 'link-group')
        .attr('id', (d, i) => `link-${i}`);
    
    // Single path that includes both line and arrowhead
    link.append('path')
        .attr('class', 'link')
        .attr('stroke', '#666')
        .attr('stroke-width', 2.5)
        .attr('fill', 'none')
        .attr('stroke-linecap', 'round')
        .attr('stroke-linejoin', 'round')
        .attr('opacity', 0.8);
    
    // Draw nodes
    const node = transformGroup.append('g')
        .selectAll('g')
        .data(nodes)
        .enter()
        .append('g')
        .attr('class', d => `node ${d.is_controllable ? 'controllable' : 'observable'}`);
    
    node.append('circle')
        .attr('r', nodeRadius)
        .attr('id', d => `node-${d.id}`)
        .attr('cx', d => d.x)
        .attr('cy', d => d.y);
    
    // Add label (property name)
    node.append('text')
        .attr('class', 'node-label')
        .attr('text-anchor', 'middle')
        .attr('x', d => d.x)
        .attr('y', d => d.y)
        .attr('dy', '-0.5em')
        .each(function(d) {
            const text = d3.select(this);
            const words = (d.property_name || d.id).split(' ');
            const nodeX = d.x; // Capture x position for use in forEach
            text.text('');
            
            const lineHeight = 1.1;
            const yOffset = -(words.length - 1) * lineHeight / 2;
            
            words.forEach((word, i) => {
                text.append('tspan')
                    .attr('x', nodeX)
                    .attr('dy', i === 0 ? `${yOffset}em` : `${lineHeight}em`)
                    .text(word);
            });
        });
    
    // Add value display
    node.append('text')
        .attr('class', 'node-value')
        .attr('id', d => `value-${d.id}`)
        .attr('text-anchor', 'middle')
        .attr('x', d => d.x)
        .attr('y', d => d.y)
        .attr('dy', '1.5em')
        .text('--');
    
    // Draw edges with static positions
    link.select('path').attr('d', d => {
        const dx = d.target.x - d.source.x;
        const dy = d.target.y - d.source.y;
        const angle = Math.atan2(dy, dx);
        const dist = Math.sqrt(dx * dx + dy * dy);
        
        // Calculate start and end points accounting for node radius
        const sourceX = d.source.x + nodeRadius * Math.cos(angle);
        const sourceY = d.source.y + nodeRadius * Math.sin(angle);
        
        // End point of the line (before arrow)
        const arrowLength = 12;
        const lineEndX = d.target.x - (nodeRadius + arrowLength) * Math.cos(angle);
        const lineEndY = d.target.y - (nodeRadius + arrowLength) * Math.sin(angle);
        
        // Draw curved path for the line
        const dr = dist * 1.5;
        let path = `M${sourceX},${sourceY}A${dr},${dr} 0 0,1 ${lineEndX},${lineEndY}`;
        
        // Add arrowhead at the end (two lines forming >)
        const arrowWidth = 7; // Slightly larger for better visibility
        // Top line of arrow
        const arrow1X = lineEndX - arrowLength * Math.cos(angle) + arrowWidth * Math.sin(angle);
        const arrow1Y = lineEndY - arrowLength * Math.sin(angle) - arrowWidth * Math.cos(angle);
        path += `M${arrow1X},${arrow1Y}L${lineEndX},${lineEndY}`;
        
        // Bottom line of arrow
        const arrow2X = lineEndX - arrowLength * Math.cos(angle) - arrowWidth * Math.sin(angle);
        const arrow2Y = lineEndY - arrowLength * Math.sin(angle) + arrowWidth * Math.cos(angle);
        path += `M${arrow2X},${arrow2Y}L${lineEndX},${lineEndY}`;
        
        return path;
    });
}

// Update visualization
function updateVisualization() {
    if (!currentData) return;
    
    const actionChain = currentData.action_chain;
    
    // Update step display
    elements.currentStepSpan.textContent = currentStep;
    
    if (currentStep === 0) {
        // Initial state
        elements.currentAction.innerHTML = `
            <div class="action-title">Initial State</div>
            <div class="action-detail">System at initial configuration</div>
        `;
        
        // Show initial values
        const initialValues = getInitialValues();
        updatePropertiesDisplay(initialValues, null);
        updateNodeValues(initialValues);
        
        // Reset graph highlighting
        d3.selectAll('.node').classed('modified', false);
        d3.selectAll('.link')
            .attr('stroke', '#666')
            .attr('stroke-width', 2.5)
            .attr('opacity', 0.8);
        
    } else {
        const action = actionChain[currentStep - 1];
        
        // Update current action display
        const passivelyChangedText = action.passively_changed && action.passively_changed.length > 0
            ? `<div class="action-detail passive">Passively affected: <strong>${action.passively_changed.join(', ')}</strong></div>`
            : '';
        
        elements.currentAction.innerHTML = `
            <div class="action-title">Step ${action.step}: ${action.action_name}</div>
            <div class="action-detail">
                Modified <strong>${action.modified_property}</strong>: 
                ${action.old_value.toFixed(2)} → ${action.new_value.toFixed(2)} 
                (${action.delta > 0 ? '+' : ''}${action.delta.toFixed(2)})
            </div>
            ${passivelyChangedText}
        `;
        
        // Update property display
        const previousValues = currentStep > 1 ? actionChain[currentStep - 2].all_values : getInitialValues();
        updatePropertiesDisplay(action.all_values, action.modified_property, action.passively_changed || [], previousValues);
        updateNodeValues(action.all_values);
        
        // Highlight modified node and passively changed nodes
        highlightModifiedNode(action.modified_property, action.passively_changed || []);
        
        // Highlight affected edges
        highlightAffectedEdges(action.modified_property);
    }
    
    // Update button states
    elements.prevBtn.disabled = currentStep === 0;
    elements.nextBtn.disabled = currentStep >= actionChain.length;

    // Update hypothesis graph for current step
    drawHypothesisGraph();
    
    // Update metrics chart highlight
    updateMetricsChartHighlight();
}

// Get initial values (matching backend logic)
function getInitialValues() {
    if (currentData.initial_values && Object.keys(currentData.initial_values).length > 0) {
        return currentData.initial_values;
    }
    return {};
}

// Update property display
function updatePropertiesDisplay(values, modifiedProperty, passivelyChanged = [], previousValues = null) {
    const graph = currentData.graph;
    const maxValue = Math.max(...Object.values(values)) * 1.2;
    
    const html = Object.keys(values).map(propName => {
        const value = values[propName];
        const node = graph.nodes[propName];
        const displayName = node.property_name || propName;
        const isModified = propName === modifiedProperty;
        const isPassive = passivelyChanged.includes(propName);
        const isFrequency = propName.toLowerCase().includes('freq');
        const percentage = (value / maxValue) * 100;
        
        let changeHtml = '';
        if (previousValues && previousValues[propName] !== undefined) {
            const change = value - previousValues[propName];
            if (Math.abs(change) > 0.01) {
                const changeClass = change > 0 ? 'positive' : 'negative';
                const changeSymbol = change > 0 ? '↑' : '↓';
                changeHtml = `<span class="property-change ${changeClass}">${changeSymbol} ${Math.abs(change).toFixed(2)}</span>`;
            }
        }
        
        // Determine CSS class based on passive state and frequency type
        let rowClass = isModified ? 'modified' : '';
        if (isPassive) {
            rowClass += isFrequency ? ' passive-freq' : ' passive';
        }
        
        return `
            <div class="property-row ${rowClass}">
                <div class="property-name">
                    ${displayName}
                    ${isPassive ? '<span class="passive-indicator" title="Passively changed">🔗</span>' : ''}
                </div>
                <div class="property-bar-container">
                    <div class="property-bar" style="width: ${percentage}%"></div>
                </div>
                <div class="property-value">
                    ${value.toFixed(2)}
                    ${changeHtml}
                </div>
            </div>
        `;
    }).join('');
    
    elements.propertiesTable.innerHTML = html;
}

// Update node values on the graph
function updateNodeValues(values) {
    for (const propName in values) {
        d3.select(`#value-${propName}`)
            .text(values[propName].toFixed(1));
    }
}

// Highlight modified node
function highlightModifiedNode(propertyName, passivelyChanged = []) {
    // Reset all node states
    d3.selectAll('.node')
        .classed('modified', false)
        .classed('passive', false)
        .classed('passive-freq', false);
    
    // Highlight actively modified node
    const circle = d3.select(`#node-${propertyName}`);
    if (!circle.empty()) {
        d3.select(circle.node().parentNode).classed('modified', true);
    }
    
    // Highlight passively changed nodes
    passivelyChanged.forEach(propName => {
        const passiveCircle = d3.select(`#node-${propName}`);
        if (!passiveCircle.empty()) {
            const nodeElement = d3.select(passiveCircle.node().parentNode);
            // Check if it's a frequency node
            const isFrequency = propName.toLowerCase().includes('freq');
            if (isFrequency) {
                nodeElement.classed('passive-freq', true);
            } else {
                nodeElement.classed('passive', true);
            }
        }
    });
}

// Highlight affected edges
function highlightAffectedEdges(sourceProperty) {
    // Reset all edges
    d3.selectAll('.link')
        .attr('stroke', '#666')
        .attr('stroke-width', 2.5)
        .attr('opacity', 0.8);
    
    const graph = currentData.graph;
    graph.edges.forEach((edge, i) => {
        if (edge.from === sourceProperty) {
            d3.select(`#link-${i} path`)
                .attr('stroke', '#667eea')
                .attr('stroke-width', 3.5)
                .attr('opacity', 1);
        }
    });
}

// Playback controls
function play() {
    if (isPlaying) return;
    
    isPlaying = true;
    elements.playBtn.disabled = true;
    elements.pauseBtn.disabled = false;
    
    playInterval = setInterval(() => {
        if (currentStep >= currentData.action_chain.length) {
            pause();
            return;
        }
        nextStep();
    }, playSpeed);
}

function pause() {
    isPlaying = false;
    elements.playBtn.disabled = false;
    elements.pauseBtn.disabled = true;
    
    if (playInterval) {
        clearInterval(playInterval);
        playInterval = null;
    }
}

function reset() {
    pause();
    currentStep = 0;
    updateVisualization();
}

function previousStep() {
    if (currentStep > 0) {
        currentStep--;
        updateVisualization();
    }
}

function nextStep() {
    if (currentStep < currentData.action_chain.length) {
        currentStep++;
        updateVisualization();
    }
}

// Error handling
function showError(message) {
    elements.currentAction.innerHTML = `
        <div class="action-title" style="color: #ff6b6b;">⚠️ Error</div>
        <div class="action-detail">${message}</div>
    `;
    console.error(message);
}

function drawMetricsChart(chartElement, metricsData, finalMetrics, bestMetrics = null, endpointMetrics = null) {
    if (!metricsData || metricsData.length === 0) {
        chartElement.innerHTML = '<div class="no-data">No metrics data available</div>';
        return;
    }

    chartElement.innerHTML = '';

    const margin = { top: 20, right: 80, bottom: 40, left: 60 };
    const width = chartElement.clientWidth - margin.left - margin.right;
    const height = chartElement.clientHeight - margin.top - margin.bottom;

    const svg = d3.select(chartElement)
        .append('svg')
        .attr('width', width + margin.left + margin.right)
        .attr('height', height + margin.top + margin.bottom);

    const g = svg.append('g')
        .attr('transform', `translate(${margin.left},${margin.top})`);

    const baseData = metricsData
        .map(d => ({
        step: d.step,
        precision: d.precision || 0,
        recall: d.recall || 0,
        f1: d.f1 || 0
    }))
        .sort((a, b) => a.step - b.step);
    const firstPoint = baseData[0];
    const lastPoint = baseData[baseData.length - 1];
    const startX = firstPoint.step - 1;
    const endX = lastPoint.step + 1;
    const startPoint = endpointMetrics && endpointMetrics.start
        ? {
            ...firstPoint,
            precision: endpointMetrics.start.precision,
            recall: endpointMetrics.start.recall,
            f1: endpointMetrics.start.f1
        }
        : firstPoint;
    const endPoint = endpointMetrics && endpointMetrics.end
        ? {
            ...lastPoint,
            precision: endpointMetrics.end.precision,
            recall: endpointMetrics.end.recall,
            f1: endpointMetrics.end.f1
        }
        : lastPoint;
    const data = [
        { ...startPoint, xStep: startX, _endpoint: 'start' },
        ...baseData.map(d => ({ ...d, xStep: d.step })),
        { ...endPoint, xStep: endX, _endpoint: 'end' }
    ];

    const minStep = startX;
    const maxStep = endX;
    const xScale = d3.scaleLinear()
        .domain([minStep, maxStep])
        .range([0, width]);
    const innerTicks = d3.ticks(firstPoint.step, lastPoint.step, Math.min(4, Math.max(2, baseData.length)));
    const tickValues = Array.from(new Set([startX, ...innerTicks, endX])).sort((a, b) => a - b);

    const yScale = d3.scaleLinear()
        .domain([0, 1])
        .nice()
        .range([height, 0]);

    const precisionLine = d3.line()
        .x(d => xScale(d.xStep))
        .y(d => yScale(d.precision))
        .curve(d3.curveMonotoneX);

    const recallLine = d3.line()
        .x(d => xScale(d.xStep))
        .y(d => yScale(d.recall))
        .curve(d3.curveMonotoneX);

    g.append('g')
        .attr('transform', `translate(0,${height})`)
        .call(
            d3.axisBottom(xScale)
                .tickValues(tickValues)
                .tickFormat(d => {
                    if (Math.abs(d - startX) < 1e-6) return 'Start';
                    if (Math.abs(d - endX) < 1e-6) return 'End';
                    return Number.isInteger(d) ? d : '';
                })
        )
        .append('text')
        .attr('x', width / 2)
        .attr('y', 35)
        .attr('fill', '#333')
        .style('text-anchor', 'middle')
        .text('Step');

    g.append('g')
        .call(d3.axisLeft(yScale).tickFormat(d3.format('.2f')))
        .append('text')
        .attr('transform', 'rotate(-90)')
        .attr('y', -45)
        .attr('x', -height / 2)
        .attr('fill', '#333')
        .style('text-anchor', 'middle')
        .text('Score');

    g.append('g')
        .attr('class', 'grid')
        .attr('transform', `translate(0,${height})`)
        .call(d3.axisBottom(xScale)
            .tickSize(-height)
            .tickFormat(''))
        .selectAll('line')
        .attr('stroke', '#e0e0e0')
        .attr('stroke-dasharray', '2,2');

    g.append('g')
        .attr('class', 'grid')
        .call(d3.axisLeft(yScale)
            .tickSize(-width)
            .tickFormat(''))
        .selectAll('line')
        .attr('stroke', '#e0e0e0')
        .attr('stroke-dasharray', '2,2');

    g.append('path')
        .datum(data)
        .attr('fill', 'none')
        .attr('stroke', '#667eea')
        .attr('stroke-width', 2.5)
        .attr('d', precisionLine);

    g.append('path')
        .datum(data)
        .attr('fill', 'none')
        .attr('stroke', '#f093fb')
        .attr('stroke-width', 2.5)
        .attr('d', recallLine);

    g.selectAll('.precision-dot')
        .data(data)
        .enter()
        .append('circle')
        .attr('class', 'precision-dot')
        .attr('cx', d => xScale(d.xStep))
        .attr('cy', d => yScale(d.precision))
        .attr('r', 3)
        .attr('fill', '#667eea');

    g.selectAll('.recall-dot')
        .data(data)
        .enter()
        .append('circle')
        .attr('class', 'recall-dot')
        .attr('cx', d => xScale(d.xStep))
        .attr('cy', d => yScale(d.recall))
        .attr('r', 3)
        .attr('fill', '#f093fb');

    const legend = g.append('g')
        .attr('transform', `translate(${width - 150}, 20)`);

    const legendData = [
        { label: 'Precision', color: '#667eea' },
        { label: 'Recall', color: '#f093fb' }
    ];

    legend.selectAll('.legend-item')
        .data(legendData)
        .enter()
        .append('g')
        .attr('class', 'legend-item')
        .attr('transform', (d, i) => `translate(0, ${i * 25})`)
        .each(function(d) {
            const item = d3.select(this);
            item.append('line')
                .attr('x1', 0)
                .attr('x2', 20)
                .attr('y1', 0)
                .attr('y2', 0)
                .attr('stroke', d.color)
                .attr('stroke-width', 2.5);
            item.append('text')
                .attr('x', 25)
                .attr('y', 4)
                .attr('fill', '#333')
                .style('font-size', '12px')
                .text(d.label);
        });

    if (finalMetrics) {
        const metricsText = g.append('g')
            .attr('transform', `translate(${width - 150}, ${height - 60})`);

        metricsText.append('text')
            .attr('fill', '#333')
            .style('font-size', '11px')
            .style('font-weight', 'bold')
            .text('Final Metrics:');

        metricsText.append('text')
            .attr('y', 18)
            .attr('fill', '#667eea')
            .style('font-size', '11px')
            .text(`Precision: ${(finalMetrics.precision * 100).toFixed(1)}%`);

        metricsText.append('text')
            .attr('y', 33)
            .attr('fill', '#f093fb')
            .style('font-size', '11px')
            .text(`Recall: ${(finalMetrics.recall * 100).toFixed(1)}%`);

        if (finalMetrics.f1 !== undefined) {
            metricsText.append('text')
                .attr('y', 48)
                .attr('fill', '#333')
                .style('font-size', '11px')
                .text(`F1: ${(finalMetrics.f1 * 100).toFixed(1)}%`);
        }

        if (bestMetrics && bestMetrics.step !== undefined) {
            metricsText.append('text')
                .attr('y', 63)
                .attr('fill', '#16a34a')
                .style('font-size', '11px')
                .style('font-weight', 'bold')
                .text(`Best: ${bestMetrics.num_correct}/${bestMetrics.num_true} (step ${bestMetrics.step})`);
        }
    }
}

function drawWeightAccuracyChart(chartElement, metricsData, finalMetrics) {
    if (!metricsData || metricsData.length === 0) {
        chartElement.innerHTML = '<div class="no-data">No weight accuracy data available</div>';
        return;
    }

    // Check if weight_accuracy data exists
    const hasWeightData = metricsData.some(d => d.weight_accuracy !== undefined);
    if (!hasWeightData) {
        chartElement.innerHTML = '<div class="no-data">No weight accuracy data available</div>';
        return;
    }

    chartElement.innerHTML = '';

    const margin = { top: 20, right: 80, bottom: 40, left: 60 };
    const width = chartElement.clientWidth - margin.left - margin.right;
    const height = chartElement.clientHeight - margin.top - margin.bottom;

    const svg = d3.select(chartElement)
        .append('svg')
        .attr('width', width + margin.left + margin.right)
        .attr('height', height + margin.top + margin.bottom);

    const g = svg.append('g')
        .attr('transform', `translate(${margin.left},${margin.top})`);

    const baseData = metricsData
        .map(d => ({
        step: d.step,
        weight_accuracy: d.weight_accuracy || 0,
        num_freq_coefficients: d.num_freq_coefficients || 0,
        num_correct_coefficients: d.num_correct_coefficients || 0
    }))
        .sort((a, b) => a.step - b.step);
    const firstPoint = baseData[0];
    const lastPoint = baseData[baseData.length - 1];
    const startX = firstPoint.step - 1;
    const endX = lastPoint.step + 1;
    const data = [
        { ...firstPoint, xStep: startX, _endpoint: 'start' },
        ...baseData.map(d => ({ ...d, xStep: d.step })),
        { ...lastPoint, xStep: endX, _endpoint: 'end' }
    ];

    const minStep = startX;
    const maxStep = endX;
    const xScale = d3.scaleLinear()
        .domain([minStep, maxStep])
        .range([0, width]);
    const innerTicks = d3.ticks(firstPoint.step, lastPoint.step, Math.min(4, Math.max(2, baseData.length)));
    const tickValues = Array.from(new Set([startX, ...innerTicks, endX])).sort((a, b) => a - b);

    const yScale = d3.scaleLinear()
        .domain([0, 1])
        .nice()
        .range([height, 0]);

    const weightLine = d3.line()
        .x(d => xScale(d.xStep))
        .y(d => yScale(d.weight_accuracy))
        .curve(d3.curveMonotoneX);

    // X axis
    g.append('g')
        .attr('transform', `translate(0,${height})`)
        .call(
            d3.axisBottom(xScale)
                .tickValues(tickValues)
                .tickFormat(d => {
                    if (Math.abs(d - startX) < 1e-6) return 'Start';
                    if (Math.abs(d - endX) < 1e-6) return 'End';
                    return Number.isInteger(d) ? d : '';
                })
        )
        .append('text')
        .attr('x', width / 2)
        .attr('y', 35)
        .attr('fill', '#333')
        .style('text-anchor', 'middle')
        .text('Step');

    // Y axis
    g.append('g')
        .call(d3.axisLeft(yScale).tickFormat(d3.format('.2f')))
        .append('text')
        .attr('transform', 'rotate(-90)')
        .attr('y', -45)
        .attr('x', -height / 2)
        .attr('fill', '#333')
        .style('text-anchor', 'middle')
        .text('Accuracy');

    // Grid lines
    g.append('g')
        .attr('class', 'grid')
        .attr('transform', `translate(0,${height})`)
        .call(d3.axisBottom(xScale)
            .tickSize(-height)
            .tickFormat(''))
        .selectAll('line')
        .attr('stroke', '#e0e0e0')
        .attr('stroke-dasharray', '2,2');

    g.append('g')
        .attr('class', 'grid')
        .call(d3.axisLeft(yScale)
            .tickSize(-width)
            .tickFormat(''))
        .selectAll('line')
        .attr('stroke', '#e0e0e0')
        .attr('stroke-dasharray', '2,2');

    // Weight accuracy line
    g.append('path')
        .datum(data)
        .attr('fill', 'none')
        .attr('stroke', '#4ade80')  // Green color
        .attr('stroke-width', 2.5)
        .attr('d', weightLine);

    // Data points
    g.selectAll('.weight-dot')
        .data(data)
        .enter()
        .append('circle')
        .attr('class', 'weight-dot')
        .attr('cx', d => xScale(d.xStep))
        .attr('cy', d => yScale(d.weight_accuracy))
        .attr('r', 4)
        .attr('fill', '#4ade80')
        .attr('stroke', '#fff')
        .attr('stroke-width', 2)
        .style('cursor', 'pointer')
        .on('mouseover', function(event, d) {
            d3.select(this).attr('r', 6);
            
            const tooltip = g.append('g')
                .attr('class', 'tooltip-weight')
                .attr('transform', `translate(${xScale(d.xStep)},${yScale(d.weight_accuracy) - 15})`);
            
            tooltip.append('rect')
                .attr('x', -60)
                .attr('y', -50)
                .attr('width', 120)
                .attr('height', 48)
                .attr('fill', 'white')
                .attr('stroke', '#4ade80')
                .attr('stroke-width', 1.5)
                .attr('rx', 4);
            
            tooltip.append('text')
                .attr('text-anchor', 'middle')
                .attr('y', -32)
                .style('font-size', '11px')
                .style('font-weight', 'bold')
                .text(`Step ${d.step}`);
            
            tooltip.append('text')
                .attr('text-anchor', 'middle')
                .attr('y', -18)
                .style('font-size', '10px')
                .text(`Accuracy: ${(d.weight_accuracy * 100).toFixed(1)}%`);
            
            tooltip.append('text')
                .attr('text-anchor', 'middle')
                .attr('y', -6)
                .style('font-size', '10px')
                .text(`Correct: ${d.num_correct_coefficients}/${d.num_freq_coefficients}`);
        })
        .on('mouseout', function() {
            d3.select(this).attr('r', 4);
            g.selectAll('.tooltip-weight').remove();
        });

    // Legend
    const legend = g.append('g')
        .attr('transform', `translate(${width + 10}, 10)`);

    legend.append('line')
        .attr('x1', 0)
        .attr('x2', 20)
        .attr('y1', 0)
        .attr('y2', 0)
        .attr('stroke', '#4ade80')
        .attr('stroke-width', 2.5);

    legend.append('text')
        .attr('x', 25)
        .attr('y', 4)
        .attr('fill', '#333')
        .style('font-size', '12px')
        .text('Weight Accuracy');

    // Final metrics display
    if (finalMetrics && finalMetrics.weight_accuracy !== undefined) {
        const metricsText = legend.append('g')
            .attr('transform', 'translate(0, 20)');

        metricsText.append('text')
            .attr('y', 0)
            .attr('fill', '#333')
            .style('font-size', '11px')
            .style('font-weight', 'bold')
            .text('Final Metrics:');

        metricsText.append('text')
            .attr('y', 16)
            .attr('fill', '#4ade80')
            .style('font-size', '11px')
            .text(`Accuracy: ${(finalMetrics.weight_accuracy * 100).toFixed(1)}%`);

        if (finalMetrics.num_freq_coefficients !== undefined) {
            metricsText.append('text')
                .attr('y', 32)
                .attr('fill', '#333')
                .style('font-size', '11px')
                .text(`Correct: ${finalMetrics.num_correct_coefficients || 0}/${finalMetrics.num_freq_coefficients}`);
        }
    }
}

function drawEdgeMetricsCharts() {
    if (!currentData || !currentData.edge_metrics) {
        elements.metricsChart.innerHTML = '<div class="no-data">No metrics data available</div>';
        elements.metricsChartFrequency.innerHTML = '<div class="no-data">No metrics data available</div>';
        elements.metricsChartWeight.innerHTML = '<div class="no-data">No metrics data available</div>';
        return;
    }

    drawMetricsChart(
        elements.metricsChart,
        currentData.edge_metrics.over_time || [],
        currentData.edge_metrics.final,
        currentData.edge_metrics.best,
        currentData.edge_metrics.endpoints
    );

    if (currentData.edge_metrics_frequency) {
        drawMetricsChart(
            elements.metricsChartFrequency,
            currentData.edge_metrics_frequency.over_time || [],
            currentData.edge_metrics_frequency.final,
            null,
            currentData.edge_metrics_frequency.endpoints
        );
    } else {
        elements.metricsChartFrequency.innerHTML = '<div class="no-data">No metrics data available</div>';
    }

    // Draw weight accuracy chart
    if (currentData.edge_metrics.over_time && currentData.edge_metrics.over_time.length > 0) {
        drawWeightAccuracyChart(
            elements.metricsChartWeight,
            currentData.edge_metrics.over_time,
            currentData.edge_metrics.final
        );
    } else {
        elements.metricsChartWeight.innerHTML = '<div class="no-data">No weight accuracy data available</div>';
    }
}

function updateMetricsChartHighlightFor(chartElement, metricsData) {
    if (!metricsData || metricsData.length === 0) {
        return;
    }

    const svg = d3.select(chartElement).select('svg');
    if (svg.empty()) return;

    const g = svg.select('g');
    if (g.empty()) return;

    g.selectAll('.step-highlight').remove();

    const currentStepData = metricsData.find(d => d.step === currentStep);
    if (!currentStepData) return;

    const margin = { top: 20, right: 80, bottom: 40, left: 60 };
    const width = chartElement.clientWidth - margin.left - margin.right;
    const height = chartElement.clientHeight - margin.top - margin.bottom;

    const minStep = d3.min(metricsData, d => d.step) - 1;
    const maxStep = d3.max(metricsData, d => d.step) + 1;
    const xScale = d3.scaleLinear()
        .domain([minStep, maxStep])
        .range([0, width]);

    const yScale = d3.scaleLinear()
        .domain([0, 1])
        .nice()
        .range([height, 0]);

    g.append('line')
        .attr('class', 'step-highlight')
        .attr('x1', xScale(currentStep))
        .attr('x2', xScale(currentStep))
        .attr('y1', 0)
        .attr('y2', height)
        .attr('stroke', '#ff6b6b')
        .attr('stroke-width', 2)
        .attr('stroke-dasharray', '4,4')
        .attr('opacity', 0.7);

    g.append('circle')
        .attr('class', 'step-highlight')
        .attr('cx', xScale(currentStep))
        .attr('cy', yScale(currentStepData.precision))
        .attr('r', 5)
        .attr('fill', '#ff6b6b')
        .attr('stroke', 'white')
        .attr('stroke-width', 2);

    g.append('circle')
        .attr('class', 'step-highlight')
        .attr('cx', xScale(currentStep))
        .attr('cy', yScale(currentStepData.recall))
        .attr('r', 5)
        .attr('fill', '#ff6b6b')
        .attr('stroke', 'white')
        .attr('stroke-width', 2);
}

// Update metrics chart highlight for current step
function updateMetricsChartHighlight() {
    if (!currentData) return;
    if (currentData.edge_metrics) {
        updateMetricsChartHighlightFor(
            elements.metricsChart,
            currentData.edge_metrics.over_time || []
        );
    }
    if (currentData.edge_metrics_frequency) {
        updateMetricsChartHighlightFor(
            elements.metricsChartFrequency,
            currentData.edge_metrics_frequency.over_time || []
        );
    }
    // Highlight weight accuracy chart
    if (currentData.edge_metrics && currentData.edge_metrics.over_time) {
        updateMetricsChartHighlightFor(
            elements.metricsChartWeight,
            currentData.edge_metrics.over_time || []
        );
    }
}

// Expose function to global scope for HTML
window.selectFolder = selectFolder;

