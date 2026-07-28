import L from 'leaflet';
import ReactDOM from 'ReactDOM';
import React from 'React';
import PropTypes from 'prop-types';
import { _ } from 'webodm/classes/gettext';
import './Road.scss';

class RoadButton extends React.Component {
  static propTypes = {
    tasks: PropTypes.array.isRequired,
    tiles: PropTypes.array.isRequired,
    map: PropTypes.object.isRequired,
    container: PropTypes.object
  }

  render(){
    return (<div>
        <a href="javascript:void(0);"
            title={_("Road")}
            className="leaflet-control-road-button leaflet-bar-part theme-secondary"></a>
    </div>);
  }
}

export default L.Control.extend({
    options: {
        position: 'topright'
    },

    onAdd: function (map) {
        var container = L.DomUtil.create('div', 'leaflet-control-road leaflet-bar leaflet-control');
        L.DomEvent.disableClickPropagation(container);
        L.DomEvent.disableScrollPropagation(container);
        ReactDOM.render(<RoadButton map={this.options.map} tasks={this.options.tasks} tiles={this.options.tiles} container={container} />, container);

        return container;
    }
});
