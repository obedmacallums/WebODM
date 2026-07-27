import L from 'leaflet';
import ReactDOM from 'ReactDOM';
import React from 'React';
import PropTypes from 'prop-types';
import { _ } from 'webodm/classes/gettext';
import './Annotations.scss';
import AnnotationsPanel from './AnnotationsPanel';

class AnnotationsButton extends React.Component {
  static propTypes = {
    tasks: PropTypes.array.isRequired,
    tiles: PropTypes.array.isRequired,
    map: PropTypes.object.isRequired
  }

  constructor(props){
    super(props);

    this.state = {
        showPanel: false
    };
  }

  handleOpen = () => {
    this.setState({showPanel: true});
  }

  handleClose = () => {
    this.setState({showPanel: false});
  }

  render(){
    const { showPanel } = this.state;

    return (<div className={showPanel ? "open" : ""}>
        <a href="javascript:void(0);"
            onClick={this.handleOpen}
            title={_("Annotations")}
            className="leaflet-control-annotations-button leaflet-bar-part theme-secondary"></a>
        <AnnotationsPanel map={this.props.map}
                      tiles={this.props.tiles}
                      isShowed={showPanel}
                      tasks={this.props.tasks}
                      onClose={this.handleClose} />
    </div>);
  }
}

export default L.Control.extend({
    options: {
        position: 'topright'
    },

    onAdd: function (map) {
        var container = L.DomUtil.create('div', 'leaflet-control-annotations leaflet-bar leaflet-control');
        L.DomEvent.disableClickPropagation(container);
        L.DomEvent.disableScrollPropagation(container);
        ReactDOM.render(<AnnotationsButton map={this.options.map} tasks={this.options.tasks} tiles={this.options.tiles} />, container);

        return container;
    }
});
